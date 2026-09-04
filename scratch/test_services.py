import sys
sys.path.insert(0, 'services/validation-service')
sys.path.insert(0, 'services/classification-service')

# pyrefly: ignore [missing-import]
from rapidfuzz import fuzz
# pyrefly: ignore [missing-import]
import main as class_main

print("=== 1. Testing Validation RapidFuzz Similarity ===")
t1 = "Coal India Limited Production Summary Rajmahal OCP Target 15.5 MT"
t2 = "Coal India Limited Production Summary Rajmahal OCP Target 15.5 MT"
sim = fuzz.token_sort_ratio(t1, t2)
print(f"Similarity: {sim}%")

print("\n=== 2. Testing Garbled Text Anomaly Logic ===")
garbled = "%%%###@@@ 12345 !@#$%^&*()"
non_space = [c for c in garbled if not c.isspace()]
alpha = [c for c in non_space if c.isalnum()]
ratio = len(alpha) / len(non_space) if non_space else 0
print(f"Garbled Alpha Ratio: {ratio:.2f}")

print("\n=== 3. Testing Defensive JSON Parsing for Classification ===")
llm_text = """```json
{
  "doc_type": "geological_survey",
  "subsidiary": "CMPDI",
  "topic_area": "borehole exploration",
  "urgency": "high"
}
```"""

parsed = class_main.clean_and_parse_json(llm_text)
print("Parsed JSON:", parsed)
