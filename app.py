import argparse
from enum import Enum
from dotenv import load_dotenv

from commands.create_db import create_db
from commands.create_pipelines import (
    create_catalog_pipeline,
    create_catalog_storage,
    create_feedback_knowledge_base,
    enable_catalog_auto_processing,
    list_models,
    register_completions_model,
    register_embedding_model,
    retrieve_catalog_demo,
    retrieve_feedback_demo,
)
from commands.reinitialize import reinitialize
from commands.seed_data import inspect_feedback_table, seed_catalog_pdf, seed_feedback_table

load_dotenv()


class Command(Enum):
    CREATE_DB = "create-db"
    CHAT = "chat"
    LIST_MODELS = "list-models"
    REGISTER_EMBEDDING_MODEL = "register-embedding-model"
    SEED_FEEDBACK_TABLE = "seed-feedback-table"
    INSPECT_FEEDBACK_TABLE = "inspect-feedback-table"
    SEED_CATALOG_PDF = "seed-catalog-pdf"
    CREATE_FEEDBACK_KB = "create-feedback-kb"
    RETRIEVE_FEEDBACK = "retrieve-feedback"
    CREATE_CATALOG_STORAGE = "create-catalog-storage"
    CREATE_CATALOG_PIPELINE = "create-catalog-pipeline"
    ENABLE_CATALOG_AUTO_PROCESSING = "enable-catalog-auto-processing"
    RETRIEVE_CATALOG = "retrieve-catalog"
    REGISTER_COMPLETIONS_MODEL = "register-completions-model"
    REINITIALIZE = "reinitialize"


# Commands that just take (args, sql_log=None) and print their own output —
# no special-casing needed for these in main() below.
SIMPLE_COMMANDS = {
    Command.CREATE_DB.value: create_db,
    Command.LIST_MODELS.value: list_models,
    Command.REGISTER_EMBEDDING_MODEL.value: register_embedding_model,
    Command.SEED_FEEDBACK_TABLE.value: seed_feedback_table,
    Command.INSPECT_FEEDBACK_TABLE.value: inspect_feedback_table,
    Command.SEED_CATALOG_PDF.value: seed_catalog_pdf,
    Command.CREATE_FEEDBACK_KB.value: create_feedback_knowledge_base,
    Command.CREATE_CATALOG_STORAGE.value: create_catalog_storage,
    Command.CREATE_CATALOG_PIPELINE.value: create_catalog_pipeline,
    Command.ENABLE_CATALOG_AUTO_PROCESSING.value: enable_catalog_auto_processing,
    Command.REGISTER_COMPLETIONS_MODEL.value: register_completions_model,
    Command.REINITIALIZE.value: reinitialize,
}


def main():
    parser = argparse.ArgumentParser(description="Application Description")

    subparsers = parser.add_subparsers(
        title="Subcommands",
        dest="command",
        help="Display available subcommands",
    )

    subparsers.add_parser(Command.CREATE_DB.value, help="Create the database and install aidb/pgfs extensions")

    # chat command — commands.chat runs Streamlit UI code at import time, so
    # it's deliberately not imported at module level (that would make every
    # other subcommand depend on Streamlit/Pillow/imgs/ being present).
    # Imported lazily below, only when this subcommand is chosen.
    subparsers.add_parser(Command.CHAT.value, help="Launch the Streamlit chat UI")

    subparsers.add_parser(Command.LIST_MODELS.value, help="List models already registered in aidb's model catalog")
    subparsers.add_parser(
        Command.REGISTER_EMBEDDING_MODEL.value,
        help="Register the NVIDIA NIM embedding model",
    )
    subparsers.add_parser(
        Command.SEED_FEEDBACK_TABLE.value,
        help="Create customer_feedback and load it from the bundled CSV (first run only)",
    )
    subparsers.add_parser(
        Command.INSPECT_FEEDBACK_TABLE.value, help="Show customer_feedback's columns and a sample of rows"
    )
    subparsers.add_parser(
        Command.SEED_CATALOG_PDF.value, help="Upload the initial catalog PDF to MinIO (first run only)"
    )
    subparsers.add_parser(Command.CREATE_FEEDBACK_KB.value, help="Build the feedback_pipeline knowledge base")

    retrieve_feedback_parser = subparsers.add_parser(
        Command.RETRIEVE_FEEDBACK.value, help="Demo aidb.retrieve_text against the feedback knowledge base"
    )
    retrieve_feedback_parser.add_argument("query", nargs="?", default=None)

    subparsers.add_parser(
        Command.CREATE_CATALOG_STORAGE.value,
        help="Connect pgfs to the MinIO bucket and create the catalogs_volume",
    )
    subparsers.add_parser(
        Command.CREATE_CATALOG_PIPELINE.value, help="Build and run the catalogs_pipeline knowledge base"
    )
    subparsers.add_parser(
        Command.ENABLE_CATALOG_AUTO_PROCESSING.value, help="Enable Background auto-processing on catalogs_pipeline"
    )

    retrieve_catalog_parser = subparsers.add_parser(
        Command.RETRIEVE_CATALOG.value, help="Demo aidb.retrieve_key against the catalog knowledge base"
    )
    retrieve_catalog_parser.add_argument("query", nargs="?", default=None)

    subparsers.add_parser(
        Command.REGISTER_COMPLETIONS_MODEL.value, help="Register the NVIDIA NIM chat completions model"
    )

    subparsers.add_parser(
        Command.REINITIALIZE.value,
        help="Reset to the initial starting point: drop aidb/pgfs and all pipeline-created tables, "
        "keeping customer_feedback and the uploaded catalog PDF(s)",
    )

    args = parser.parse_args()

    if args.command == Command.CHAT.value:
        from commands.chat import chat
        from commands.create_pipelines import COMPLETIONS_MODEL_NAME

        register_completions_model()
        chat(args, COMPLETIONS_MODEL_NAME)
    elif args.command == Command.RETRIEVE_FEEDBACK.value:
        retrieve_feedback_demo(query=args.query)
    elif args.command == Command.RETRIEVE_CATALOG.value:
        retrieve_catalog_demo(query=args.query)
    elif args.command in SIMPLE_COMMANDS:
        SIMPLE_COMMANDS[args.command](args)
    else:
        print("Invalid command. Use '--help' for assistance.")


if __name__ == "__main__":
    main()
