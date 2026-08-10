# OCR evaluation — chandra

| | |
| --- | --- |
| engine | `chandra` |
| output_dir | `/Users/duyseu/Workspace/Lab/ocr-core/output/high_quality_handwritten` |
| ground_truth_dir | `/Users/duyseu/Workspace/Lab/ocr-core/ground_truth/handwritten` |
| IoU threshold | 0.5 |
| documents found | 1 |
| scored for text | 1 |
| scored for layout | 0 |

## 1 · Text, document-level  (predicted .md vs ground truth; lower is better)

| doc | CER | CER tone-blind | WER | n_chars | n_empty_gold | ground truth |
| --- | --- | --- | --- | --- | --- | --- |
| tonghopdon | 0.0565 | 0.0517 | 0.1019 | 47178 | 0 | tonghopdon.md |
| **all documents pooled** | **0.0565** | **0.0517** | **0.1019** | **47178** | **0** | — |

## 2 · Layout / bbox  (IoU >= 0.5; higher is better)

Not scored for any document. Per-document reason:

| doc | reason |
| --- | --- |
| tonghopdon | chandra <stem>_metadata.json carries page_box and token counts only, no per-element bbox: layout metrics cannot be computed from it |

## 3 · Text, element-level  (matched boxes only — read next to layout recall above)

| doc | CER | CER tone-blind | WER | n_elements | n_chars |
| --- | --- | --- | --- | --- | --- |
| tonghopdon | n/a | n/a | n/a | 0 | 0 |

## 4 · Not measured

### 4.1 Per document

| doc | what is missing |
| --- | --- |
| tonghopdon | chandra <stem>_metadata.json carries page_box and token counts only, no per-element bbox: layout metrics cannot be computed from it |

### 4.2 Per page

None.

### 4.3 Metrics out of scope for this run

| metric | why |
| --- | --- |
| Table — TEDS, TEDS-Struct | out of scope for this run; metrics/table.py is unwired |
| Picture — detection, caption | out of scope for this run |

### 4.4 Ground truth with no prediction

None — every ground-truth file was paired.
