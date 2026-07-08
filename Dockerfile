FROM python:3.11-slim

# Create user to run the app (Hugging Face Spaces requires this)
RUN useradd -m -u 1000 user

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copy all files with correct ownership
COPY --chown=user . $HOME/app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories for sqlite and chromadb with full permissions
RUN mkdir -p $HOME/app/data $HOME/app/chroma_db
RUN chmod -R 777 $HOME/app

# Expose port 7860 (Hugging Face Spaces default)
EXPOSE 7860

# Run FastAPI using uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
