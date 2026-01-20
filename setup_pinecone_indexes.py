# setup_pinecone_indexes.py
# Create Pinecone indexes for all corpus types
# ----------------------------------------------------------------------

from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec
from pinecone_config import (
    PINECONE_API_KEY,
    PINECONE_ENVIRONMENT,
    PINECONE_INDEX_RESUMES,
    PINECONE_INDEX_JOBS,
    PINECONE_INDEX_TRAINING,
    PINECONE_INDEX_ASSISTANCE,
    VECTOR_DIMENSION,
    PINECONE_METRIC,
    PINECONE_CLOUD,
    PINECONE_REGION,
    validate_config,
)

def create_pinecone_indexes():
    """Create all required Pinecone indexes"""
    
    # Validate configuration
    errors = validate_config()
    if errors:
        print("❌ Configuration errors:")
        for error in errors:
            print(f"   - {error}")
        print("\n💡 Fix: Set PINECONE_API_KEY in your .env file")
        print("   Get one from: https://www.pinecone.io/")
        return False
    
    print("✅ Configuration valid")
    print(f"   API Key: ***{PINECONE_API_KEY[-4:]}")
    print(f"   Environment: {PINECONE_ENVIRONMENT}")
    print(f"   Vector Dimension: {VECTOR_DIMENSION}")
    print()
    
    # Initialize Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)
    
    # List existing indexes
    existing_indexes = [idx.name for idx in pc.list_indexes()]
    print(f"📊 Existing indexes: {existing_indexes or '(none)'}")
    print()
    
    # Indexes to create
    indexes_to_create = [
        (PINECONE_INDEX_RESUMES, "Resume vectors (for j_to_r, p_to_r, a_to_r)"),
        (PINECONE_INDEX_JOBS, "Job description vectors (for r2j)"),
        (PINECONE_INDEX_TRAINING, "Training post vectors (for r_to_p)"),
        (PINECONE_INDEX_ASSISTANCE, "Assistance post vectors (for r_to_A)"),
    ]
    
    for index_name, description in indexes_to_create:
        if index_name in existing_indexes:
            print(f"⏭️  Index '{index_name}' already exists - skipping")
            continue
        
        print(f"🔨 Creating index: {index_name}")
        print(f"   Description: {description}")
        
        try:
            pc.create_index(
                name=index_name,
                dimension=VECTOR_DIMENSION,
                metric=PINECONE_METRIC,
                spec=ServerlessSpec(
                    cloud=PINECONE_CLOUD,
                    region=PINECONE_REGION
                )
            )
            print(f"   ✅ Created successfully!")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        print()
    
    # List final indexes
    final_indexes = [idx.name for idx in pc.list_indexes()]
    print("=" * 60)
    print(f"✅ Setup complete! Total indexes: {len(final_indexes)}")
    print()
    print("📋 Your Pinecone indexes:")
    for idx in pc.list_indexes():
        print(f"   - {idx.name} ({idx.dimension}d, {idx.metric})")
    print()
    print("🎯 Next steps:")
    print("   1. Run admin ingestion tools to add data")
    print("   2. Run ENHANCED user search modules")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("  PINECONE INDEX SETUP")
    print("=" * 60)
    print()
    
    success = create_pinecone_indexes()
    
    if not success:
        print("\n⚠️  Setup failed. Please fix errors and try again.")
        exit(1)
    else:
        print("\n🎉 All done! You're ready to use Pinecone.")

