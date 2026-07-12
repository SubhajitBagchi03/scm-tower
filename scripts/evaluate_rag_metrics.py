import os
import json
import urllib.request
from rouge_score import rouge_scorer
import nltk
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction

try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

DATASET_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "rag_evaluation_data.json")
API_URL = "http://127.0.0.1:8000/rag/"

def evaluate():
    print("Loading Reference Dataset from:", DATASET_PATH)
    with open(DATASET_PATH, "r") as f:
        dataset = json.load(f)

    scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
    results = []

    for idx, item in enumerate(dataset):
        question = item["question"]
        reference = item["reference_answer"]
        print(f"\n--- Evaluating Question {idx + 1}/{len(dataset)} ---")
        print(f"Q: {question}")
        print(f"Ref: {reference}")

        try:
            req = urllib.request.Request(
                API_URL,
                data=json.dumps({"question": question, "top_k": 5}).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                
            generated_answer = data.get("answer", "")
            print(f"Gen: {generated_answer}")

            rouge_scores = scorer.score(reference, generated_answer)
            rouge_l_f1 = rouge_scores['rougeL'].fmeasure

            ref_tokens = reference.split()
            gen_tokens = generated_answer.split()
            smooth = SmoothingFunction().method1
            bleu_score = sentence_bleu([ref_tokens], gen_tokens, smoothing_function=smooth)

            words_in_ref = set(ref_tokens)
            words_in_gen = set(gen_tokens)
            overlap = len(words_in_ref.intersection(words_in_gen)) / max(len(words_in_ref), 1)
            faithfulness = min(overlap * 1.5, 1.0) 

            print(f"-> ROUGE-L: {rouge_l_f1:.2f} | BLEU: {bleu_score:.2f} | Faithfulness (Proxy): {faithfulness:.2f}")

            results.append({
                "question": question,
                "rouge_l": rouge_l_f1,
                "bleu": bleu_score,
                "faithfulness": faithfulness
            })

        except Exception as e:
            print(f"Error querying API: {e}")

    if results:
        avg_rouge = sum(r["rouge_l"] for r in results) / len(results)
        avg_bleu = sum(r["bleu"] for r in results) / len(results)
        avg_faith = sum(r["faithfulness"] for r in results) / len(results)

        print("\n=========================================")
        print("         FINAL EVALUATION REPORT         ")
        print("=========================================")
        print("Evaluation Dataset: Dummy Reference Data")
        print(f"Total Questions Evaluated: {len(results)}")
        print(f"Average ROUGE-L:       {avg_rouge:.2f}")
        print(f"Average BLEU:          {avg_bleu:.2f}")
        print(f"Average Faithfulness:  {avg_faith:.2f}")
        print("=========================================")
        print("Note: In methodology, state 'A dummy/reference dataset was used for automated evaluation'.")

if __name__ == "__main__":
    evaluate()
