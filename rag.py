from db import get_connection

template = """You are a friendly assistant for ACME Bank, helping answer questions about
customer feedback and ACME's product catalog (savings, cards, loans, and investment accounts).
Use the following piece of context to answer the question.
If the context is empty, try your best to answer without it.
Never mention the context.
Try to keep your answers concise unless asked to provide details.

Context: {context}
Question: {question}"""

def retrieve_feedback_context(cursor, query_str, topk):
    # feedback_pipeline is a Table-sourced pipeline, so retrieve_text can
    # resolve matched chunks directly from the source column.
    cursor.execute(
        "SELECT value FROM aidb.retrieve_text('public.pipeline_feedback_pipeline', %s, %s);",
        (query_str, topk),
    )
    return [row[0] for row in cursor.fetchall()]


def retrieve_catalog_context(cursor, query_str, topk):
    # catalogs_pipeline is a Volume-sourced (PDF) pipeline: retrieve_text would
    # return the raw source file bytes, so matched chunks come from retrieve_key
    # joined back to the catalog_chunks intermediate table instead.
    cursor.execute(
        """WITH retrieve_key AS (
                    SELECT * FROM aidb.retrieve_key('public.pipeline_catalogs_pipeline', %s, topk => %s)
                )
                SELECT c.value
                FROM retrieve_key r
                JOIN catalog_chunks c ON r.part_ids[1:2] = c.part_ids
                WHERE r.part_ids[3] = 0;""",
        (query_str, topk),
    )
    return [row[0] for row in cursor.fetchall()]


def retrieve_augmentation(query, topk):
    # query is the question to ask
    # topk is the number of documents to retrieve per knowledge base
    # clean punctuations and extra spaces
    query_str = ''.join(e for e in query if e.isalnum() or e.isspace())
    with get_connection() as conn:
        with conn.cursor() as cursor:
            feedback_chunks = retrieve_feedback_context(cursor, query_str, topk)
            catalog_chunks = retrieve_catalog_context(cursor, query_str, topk)
        conn.commit()

    sections = []
    if feedback_chunks:
        sections.append("Customer feedback:\n" + '\n'.join(feedback_chunks))
    if catalog_chunks:
        sections.append("Product catalog:\n" + '\n'.join(catalog_chunks))
    return '\n\n'.join(sections)

def rag_query(aidb_model_name, query, topk):
    # topk is the number of documents to retrieve per knowledge base
    # query is the question to ask

    rag_query = retrieve_augmentation(query, topk)
    query_template = template.format(context=rag_query, question=query)
    
    conn = get_connection()
    with conn.cursor() as cur:
        query_decode = "SELECT decode_text FROM aidb.decode_text(%s, %s);"

        cur.execute(query_decode, (aidb_model_name, query_template,))
        result = cur.fetchone()
        return result[0]
    