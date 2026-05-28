from langchain_community.document_loaders import PyMuPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import settings


def load_and_chunk(pdf_path: str) -> list[Document]:
    """Match the splitter config from rag_system/index_pdf.py exactly."""
    pages = PyMuPDFLoader(file_path=pdf_path).load()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""],
        add_start_index=True,
    )
    return splitter.split_documents(documents=pages)
