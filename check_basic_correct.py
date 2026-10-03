#!/usr/bin/env python3

# Let's manually calculate what the CORRECT implementation should produce
# for the basic contamination test

# Basic contamination test data after processing:
# Original data:
#   id,feature1,feature2,split
#   1,A,10,train    -> index 0
#   2,B,20,train    -> index 1
#   3,C,30,test     -> index 2
#   4,A,10,test     -> index 3  (same canonical row as index 0)
#   5,D,40,train    -> index 4

# After processing for hashing (excluding split column and ID column):
#   feature1,feature2
#   A,10    -> hash1 (indices 0, 3)
#   B,20    -> hash2 (index 1)
#   C,30    -> hash3 (index 2)
#   A,10    -> hash1 (indices 0, 3)
#   D,40    -> hash4 (index 4)

# For the contamination finding (hash1):
#   Group indices: [0, 3]
#   Group split values: ['train', 'test']
#     - Index 0 in group (original index 0): 'train'
#     - Index 1 in group (original index 3): 'test'

print("Basic contamination test analysis:")
print("=" * 50)
print("Data after processing (for hashing):")
print("Index: feature1,feature2 -> split")
print("0: A,10 -> train")
print("1: B,20 -> train")
print("2: C,30 -> test")
print("3: A,10 -> test  <- same canonical row as index 0")
print("4: D,40 -> train")
print()
print("Contamination group (hash1): indices [0, 3]")
print("  Index 0: original index 0, values A,10, split=train")
print("  Index 1: original index 3, values A,10, split=test")
print()
print("If we show ALL occurrences (current implementation):")
print("  train: [0, 3]  <- all indices where canonical row appears")
print("  test: [0, 3]   <- all indices where canonical row appears")
print()
print("If we show INDICES PER SPLIT (what some tests expect):")
print("  train: [0]     <- indices in group where split='train'")
print("  test: [3]      <- indices in group where split='test'")
print()
print("Current test expects:")
print("  train: [0, 3]")
print("  test: [0, 3]")
print()
print("So the current test expects the 'show ALL occurrences' approach")