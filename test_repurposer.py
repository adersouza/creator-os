import sys
from pathlib import Path

# Add python_packages to sys.path
sys.path.append(str(Path(__file__).parent / "python_packages"))

from campaign_factory.repurposer import VariantPipeline

def main():
    master_path = Path("dummy_master.mp4")
    # Touch dummy file
    master_path.touch()
    
    pipeline = VariantPipeline(master_path, target_count=3, platform="tiktok")
    variants = pipeline.generate_batch("tiktok_aggressive")
    
    print("\n[Test Complete] Generated Variants:")
    for v in variants:
        print(f" - {v}")

if __name__ == "__main__":
    main()
