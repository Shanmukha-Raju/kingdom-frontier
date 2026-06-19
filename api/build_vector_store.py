import os
import faiss
from uuid import uuid4
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
load_dotenv("openai.env")
vector_store_path = os.path.join("data", "vector_store")
def load_or_build_vector_store(api_key=None):
    # 2. Changed dimensions from 3072 to 384 to match all-MiniLM-L6-v2
    index = faiss.IndexFlatL2(384)
    # 3. Swapped OpenAI out for the free local Hugging Face model
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    if os.path.exists(vector_store_path):
        print("Loading vector store from disk...")
        vector_store = FAISS.load_local(vector_store_path, embeddings, allow_dangerous_deserialization=True)
    else:
        print("Building new vector store...")
        vector_store = FAISS(
            embedding_function=embeddings,
            index=index,
            docstore=InMemoryDocstore(),
            index_to_docstore_id={}
        )
        # Determine correct file path based on execution location
        facts_file = os.path.join("api", "world_facts.txt")
        if not os.path.exists(facts_file):
            facts_file = "world_facts.txt" # Fallback if already running inside the /api folder
            
        # Load world facts
        with open(facts_file, "r") as file:
            facts = [line.strip() for line in file if line.strip()]
            
        documents = [Document(page_content=fact) for fact in facts]
        uuids = [str(uuid4()) for _ in range(len(documents))]
        vector_store.add_documents(documents=documents, ids=uuids)
        FAISS.save_local(vector_store, vector_store_path)

    return vector_store

if __name__ == "__main__":
    load_dotenv()
    load_or_build_vector_store()
    print("Vector store is ready.")