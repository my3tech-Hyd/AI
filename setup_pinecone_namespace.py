# setup_pinecone_namespace.py
# Create ONE Pinecone index with namespaces for all corpus types
# (Better approach - saves on index limit!)
# ----------------------------------------------------------------------

from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec
from pinecone_config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE_RESUMES,
    PINECONE_NAMESPACE_JOBS,
    PINECONE_NAMESPACE_TRAINING,
    PINECONE_NAMESPACE_ASSISTANCE,
    VECTOR_DIMENSION,
    PINECONE_METRIC,
    PINECONE_CLOUD,
    PINECONE_REGION,
    validate_config,
)

def setup_pinecone():
    """Create Pinecone index with namespaces"""
    
    # Validate configuration
    errors = validate_config()
    if errors:
        print("Error: Configuration errors:")
        for error in errors:
            print(f"   - {error}")
        print("\nFix: Set PINECONE_API_KEY in your .env file")
        print("   Get one from: https://www.pinecone.io/")
        return False
    
    print("Configuration valid")
    print(f"   API Key: ***{PINECONE_API_KEY[-4:]}")
    print(f"   Index Name: {PINECONE_INDEX_NAME}")
    print(f"   Vector Dimension: {VECTOR_DIMENSION}")
    print()
    
    # Initialize Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    
    # List existing indexes
    existing_indexes = [idx.name for idx in pc.list_indexes()]
    print(f"Existing indexes: {existing_indexes or '(none)'}")
    print()
    
    # Create index if it doesn't exist
    if PINECONE_INDEX_NAME in existing_indexes:
        print(f"Index '{PINECONE_INDEX_NAME}' already exists - skipping creation")
        index = pc.Index(PINECONE_INDEX_NAME)
    else:
        print(f"Creating index: {PINECONE_INDEX_NAME}")
        
        try:
            pc.create_index(
                name=PINECONE_INDEX_NAME,
                dimension=VECTOR_DIMENSION,
                metric=PINECONE_METRIC,
                spec=ServerlessSpec(
                    cloud=PINECONE_CLOUD,
                    region=PINECONE_REGION
                )
            )
            print(f"   Created successfully!")
            index = pc.Index(PINECONE_INDEX_NAME)
        except Exception as e:
            print(f"   Error: {e}")
            return False
    
    print()
    print("=" * 60)
    print(f"Setup complete!")
    print()
    print(f"Index: {PINECONE_INDEX_NAME}")
    print(f"  Dimension: {VECTOR_DIMENSION}")
    print(f"  Metric: {PINECONE_METRIC}")
    print()
    print("Namespaces to use:")
    print(f"  - {PINECONE_NAMESPACE_RESUMES} (for resumes)")
    print(f"  - {PINECONE_NAMESPACE_JOBS} (for job descriptions)")
    print(f"  - {PINECONE_NAMESPACE_TRAINING} (for training posts)")
    print(f"  - {PINECONE_NAMESPACE_ASSISTANCE} (for assistance posts)")
    print()
    print("Next steps:")
    print("  1. Run admin ingestion tools to add data")
    print("  2. Run user search modules")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("  PINECONE SETUP (NAMESPACE-BASED)")
    print("=" * 60)
    print()
    
    success = setup_pinecone()
    
    if not success:
        print("\nSetup failed. Please fix errors and try again.")
        exit(1)
    else:
        print("\nAll done! You're ready to use Pinecone.")

