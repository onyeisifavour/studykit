import re
import os

def add_answer_method_tags(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    
    lines = content.strip().split('\n')
    new_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Match lines like "1. A [Type: MCQ]" or "10. 12 [Type: Hybrid]" or "26. (a) ... [Type: Theory]"
        match = re.match(r'^(\d+)\.\s+(.+?)\s+\[Type:\s+(MCQ|Hybrid|Theory)\]', line)
        if match:
            num = match.group(1)
            answer = match.group(2)
            qtype = match.group(3)
            if qtype in ['MCQ', 'Hybrid']:
                method = 'text-exclusive'
            else:
                method = 'non-text-exclusive'
            new_line = f"{num}. {answer} [Type: {qtype}] [Answer-Method: {method}]"
            new_lines.append(new_line)
        else:
            new_lines.append(line)
    
    with open(filepath, 'w') as f:
        f.write('\n'.join(new_lines) + '\n')

# Process all answer banks
base = '/home/favour/Desktop/Learning/Resources/virtuals_and_code/quiz-ecosystem/quiz_app/X'
for root, dirs, files in os.walk(base):
    for f in files:
        if f == 'answer_bank.txt':
            filepath = os.path.join(root, f)
            add_answer_method_tags(filepath)
            print(f"Processed: {filepath}")

print("Done!")
