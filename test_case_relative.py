#!/usr/bin/env python3

# Test what relative indices would produce for case insensitive test

print("Testing what RELATIVE indices would produce for case insensitive test:")

# Case insensitive test scenario after processing:
# Original data:
#   Row 0: 'A', 10, 'TRAIN'
#   Row 1: 'A', 10, 'Test'
# After processing (strip + lower):
#   Row 0: 'A', 10, 'train'
#   Row 1: 'A', 10, 'test'

print("Data:")
print("Original index 0: 'A', 10, 'TRAIN' -> processed: 'A', 10, 'train'")
print("Original index 1: 'A', 10, 'Test' -> processed: 'A', 10, 'test'")
print()

print("Both rows have same canonical row: 'A', 10")
print("Split values after processing: ['train', 'test']")
print()

print("Contamination group: both rows (original indices [0, 1])")

print("If we show RELATIVE indices within each split group:")
print("  Train split occurrences: original index 0")
print("    In train group: [original index 0] -> position 0")
print("  Test split occurrences: original index 1")
print("    In test group: [original index 1] -> position 0")
print("  Result: train: [0], test: [0]")
print()

print("But case insensitive test EXPECTS:")
print("  train: [0]  # Absolute index 0")
print("  test: [1]   # Absolute index 1")
print()

print("So relative indices would give train: [0], test: [0]")
print("But test expects train: [0], test: [1]")
print("So relative indices would FAIL case insensitive test on the test split")