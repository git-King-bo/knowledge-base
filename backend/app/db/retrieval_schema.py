"""Cover source-scoped lookups and vector metadata without reading vector bodies."""
from sqlalchemy import Index,MetaData,Table,inspect


def upgrade_retrieval_indexes(connection):
    inspector=inspect(connection)
    tables=set(inspector.get_table_names())
    for table_name,name,columns in (
        ('knowledge_chunks','ix_knowledge_chunks_source_index',('source_id','chunk_index')),
        ('knowledge_chunk_embeddings','ix_chunk_embeddings_model_dimension',('embedding_model','embedding_dim','chunk_id')),
    ):
        if table_name not in tables:continue
        if name in {i['name'] for i in inspector.get_indexes(table_name)}:continue
        table=Table(table_name,MetaData(),autoload_with=connection)
        Index(name,*(table.c[c] for c in columns)).create(connection,checkfirst=True)
