# Evaluation harness

Scores predictions against one ground-truth dataset, one tier at a time: Detection & Layout, Recognition, Extraction & Structure (see [`docs/README.md`](../docs/specs/benchmark-ocr.md)). Only Recognition is implemented; `layout/` and `extraction/` hold the planned input and metrics and fail by name when run.

Nothing here imports `core`. The evaluator reads files an engine already wrote, so it scores any provider without knowing how the files were produced. The engine name is only a label in the report path.

## Running

```bash
python -m evaluate recognition                              # pred + GT dirs from ./config.yaml
python -m evaluate recognition --pred data/output/chandra/lpbank --gt data/ground_truth/lpbank --label chandra
python -m evaluate recognition --doc tonghopdon             # one document, by doc_id
python -m evaluate recognition --table-threshold 0.7        # stricter table pairing (default 0.5)
python -m evaluate recognition --config other.yaml          # a different config file
```

The report is written to `data/results/<tier>/<label>/<dataset>.md`, where `label` defaults to the name of the prediction directory and `dataset` is the name of the ground-truth directory. Predictions live in `data/output/<engine>/<dataset>/`, so the default label is the dataset name: pass `--label <engine>`. A directory not given on the command line falls back to `output_dir` / `ground_truth_dir` in `config.yaml`, resolved from the repo root. Everything else in that file belongs to the pipeline and is ignored.

## Ground-truth dataset

Each document is two files side by side in `data/ground_truth/<dataset>/`:

```text
<doc_id>.json    doc_id, file, metadata, normalization_version, text_file, pages, fields
<doc_id>.md      the transcription, <table> markup and <!-- image --> markers included
```

The JSON follows the schema in [`docs/specs/benchmark-ocr.md`](../docs/specs/benchmark-ocr.md), except that `full_text` is replaced by `text_file`, the name of the markdown beside it, so a reviewer edits markdown rather than a JSON string. `pages` and `fields` may stay empty until a document is annotated. A record with invalid JSON, without `doc_id` or `text_file`, whose markdown is missing, or sharing a `doc_id` with another record stops the run and is named.

Loose `.md`, `.txt` or `.docx` ground truth converts once:

```bash
python -m evaluate.ground_truth data/ground_truth/lpbank --source-dir data/raw/lpbank
python -m evaluate.ground_truth data/ground_truth/printed --out data/ground_truth/printed_ds --source-dir data/raw/printed/high_quality
```

A `.md` converts in place (only the `.json` is added). A `.docx` or `.txt` needs `--out` pointing to another directory, since a `.md` beside it would give `finetune/` two files with one stem. In a `.docx` the body is walked in order, paragraphs as paragraphs and tables as `<table>` markup with spans, each merged cell once. `--source-dir` fills `file` with the original document of the same stem. An existing `.json` is never overwritten.

## Pairing

The Recognition tier reads every `*.md` under the prediction directory, recursively, and pairs it with the record of the same `doc_id` (the filename stem). Anything unpaired on either side is listed in the report rather than dropped: a silent drop and a perfect score look identical in a total. Two predictions sharing a stem is an error, not a silent pick. Text below `<!-- ann-aside -->` in a prediction (page headers, footers, footnotes gathered by the core pipeline) is not scored.

## Evaluation principles

These principles follow sections 1.3-1.4 of `benchmark_ocr_rag_agent.md`. Each tier is described in the same order: metrics, normalization, how it is computed (with an example per metric), notes on reading the results.

### Detection & Layout

### Recognition

#### Metrics

| Metric | What it measures | Better | Range |
|---|---|---|---|
| **WER** | Share of wrong words, after normalization | Lower | 0 to **can exceed 1** |
| **TEDS** | How close a table is to the GT, structure and cell text together | Higher | 0 to 1 |

Next to WER the report prints an `ignored` column: the number of prediction words skipped because they sit exactly where an image marker is in the GT (see WER below). This column is not a metric. It says how many words the markers skipped.

Next to TEDS the report prints **three count columns**. They are not metrics, but TEDS must always be read with them:

- `matched`: number of pred-GT table pairs that were paired.
- `n_gold`: number of tables in the GT.
- `n_pred`: number of tables in the prediction.

#### Normalization

Code: `recognition/normalize.py`. Applied identically to both sides.

**GT-only step for WER**, function `mark_images` (runs before step 1):

0. Turn each `<!-- image -->` marker into a placeholder token (character `U+E000`). This token survives every later normalization step. TEDS does not run this step, so for TEDS the marker is removed in step 2 like any other comment.

**Shared steps for WER and TEDS**, function `strip_figures`:

1. Unicode to NFC.
2. Remove HTML comments `<!-- ... -->`.
3. Remove markdown images `![alt](url)`, alt text included.
4. Remove chandra-style figure descriptions `[hình: ...]`.

**Extra steps for WER**, function `strict`:

5. Turn links `[text](url)` into `text`.
6. Remove inline tags (`sup`, `sub`, `b`, `i`, `u`, `em`, `strong`, `span`, `a`, `code`, `small`, `mark`) **without** inserting a space, so `m<sup>2</sup>` becomes `m2`.
7. Replace every other HTML tag (`<td>`, `<tr>`, `<p>`, `<br>`...) with **one space**.
8. Decode HTML entities: `&amp;` becomes `&`.
9. Remove the heading mark `#` at the start of a line and the bullet mark at the start of a line (`-`, `*`, `+`, `1.`).
10. Remove **every** `*`, `_`, `` ` `` character, wherever it is.
11. Move tone marks to the traditional position: `hoà` becomes `hòa`, `thuỷ` becomes `thủy`. Two exceptions:
    - not after `q` (`quý` stays as is);
    - not when a letter follows (`khoản`, `hoạt` stay as is).
12. Collapse all whitespace and line breaks into one space.

#### WER

Code: `recognition/wer.py`.

```
WER = (S + D + I) / N
```

- S = substituted words, D = deleted words, I = inserted words. All three come from the Levenshtein distance over the word lists.
- N = number of GT words, **not counting** image marker tokens.
- A "word" is a space-separated chunk after normalization. Punctuation stays attached to the word.
- Each document is joined into one string before comparison.
- An empty pred counts as 0 words, so WER = 1.
- A document whose GT is empty after normalization is left out. A GT with only image markers also counts as empty.
- **Pooled row** = Σ word errors / Σ GT words (principle C4). The `ignored` value of the pooled row is the sum over documents.

**Image markers in the GT: skip text the engine read from an image**

Screenshots, diagrams and stamps often contain text. The GT may not transcribe it, but the engine still reads it, or writes a sentence describing the image. Left alone, every one of those words is an insertion error. The handling:

1. **In the GT**, put `<!-- image -->` on its own line, **at the image's position** in reading order.
2. For WER, the marker becomes a **wildcard word**. It matches any run of consecutive prediction words (the empty run included) at **cost 0**. Words matched this way are counted in the `ignored` column.
3. Alignment:
   - Align the whole text with Levenshtein and keep matching runs of **3 words or more** as anchors. Shorter matches are not anchors, so a word inside the image that happens to equal a nearby GT word does not split the image region in two.
   - Each gap between two anchors that contains a marker is realigned exactly by dynamic programming, with the marker as a wildcard.
   - A gap without a marker uses plain Levenshtein. A document with no markers therefore gets exactly the WER it had before this mechanism existed.
   - When several alignments have the same cost, pick the one that skips the **fewest words**, so the `ignored` column is not inflated.
4. A marker **never skips a GT word.** A misread GT word next to an image still costs 1 error: the substitution only turns into a deletion, at the same cost. Only prediction words **with no counterpart in the GT** are skipped.

Rules for placing markers in the GT:

- One marker per image.
- Only mark images whose inner text you **do not want scored**. If the text in the image must be scored (for example a contract number on a stamp), transcribe it into the GT and do not add a marker. Never both.
- A marker inside a table cell does not affect TEDS (it is removed like any comment).

**Example: images in a document.** Images written as `![..](..)` and `[hình: ...]` are removed on both sides. Text read from an image that the GT does not transcribe is only skipped when the GT has a marker at that position.

| Pred | GT | WER | `ignored` | Note |
|---|---|---|---|---|
| `Bên vay ![logo](a.png) cam kết` | `Bên vay cam kết` | **0** | 0 | The markdown image is removed. |
| `Bên vay [hình: Con dấu tròn màu đỏ] cam kết` | `Bên vay cam kết` | **0** | 0 | The `[hình: ...]` description is removed. |
| `Bên vay` ⏎ `The screenshot shows a stamp` ⏎ `cam kết` | `Bên vay cam kết` | **1.25** | 0 | No marker in the GT, so the 5 description words are insertions. |
| `Bên vay` ⏎ `The screenshot shows a stamp` ⏎ `cam kết` | `Bên vay` ⏎ `<!-- image -->` ⏎ `cam kết` | **0** | 5 | With the marker, those 5 words are skipped. |
| `Bên vay cam kết` | `Bên vay` ⏎ `<!-- image -->` ⏎ `cam kết` | **0** | 0 | An engine that reads nothing from the image is not penalized either. |
| `Bên vey Con dấu đỏ cam kết` | `Bên vay` ⏎ `<!-- image -->` ⏎ `cam kết` | **0.25** | 3 | The image text is skipped, but `vey` is still an error. |
| `Bên vay cam kết Con dấu đỏ` | `Bên vay` ⏎ `<!-- image -->` ⏎ `cam kết` | **0.5** | 3 | The engine put the image text in the **wrong place**: the cheapest path skips all of `cam kết Con dấu đỏ` and charges 2 deletions for the GT's `cam kết`. |

#### TEDS

Code: `recognition/tables.py`.

**1. Extract tables.**

- Take every outermost `<table>`; a table nested in another table counts as part of its parent.
- Take every markdown table of the form `| a | b |` and convert it to HTML.

**2. Build the tree.**

- The tree has the shape `table -> tr -> td`.
- `<th>` becomes `<td>`.
- `thead`, `tbody`, `tfoot` are dropped and their children lifted one level up.

**3. Tree edit distance** (APTED algorithm, PubTabNet cost model):

| Operation | Cost |
|---|---|
| Insert or delete a node (row, cell) | 1 |
| Two nodes with different tags, or different `colspan`/`rowspan` | 1 |
| Two cells with the same tag and span but different text | Normalized Levenshtein (0..1) between the two texts |

```
TEDS = max(0, 1 - distance / node count of the larger tree)
```

**4. Pair predicted tables with GT tables.** There are no boxes, so pairing is by content:

1. For every (pred table, GT table) pair, compute TEDS and a **structure score**: the same TEDS formula but treating every cell's text as equal. The structure score is only used internally for pairing and is not reported.
2. Sort the pairs descending by (structure score, then TEDS).
3. Pair **greedily** from the top. Each table is paired at most once.
4. Stop when the next pair's structure score is **< 0.5** (change it with `--table-threshold`).
5. If pred tables × GT tables > 2000, skip pairing and write the reason in the `note` column.

**5. Score of one document**: TEDS = mean **over the paired tables only**.

**6. Pooled row**: TEDS = Σ(document TEDS × matched) / Σ matched, a mean weighted by the number of pairs.

**Images in tables.** Images, `[hình: ...]` descriptions and `<!-- image -->` markers are removed from the cell text before comparison (steps 2-4 under Normalization). The image marker **does not** act as a wildcard in TEDS. If the engine reads text from an image inside a cell, that text still makes the cell differ from the GT.

**Example.** The GT is a 2×2 table: `[Kỳ hạn | Lãi suất] / [6 tháng | 5,5%]`. Its tree has 7 nodes: 1 table + 2 tr + 4 td.

| Pred | TEDS | matched / n_gold / n_pred | Explanation |
|---|---|---|---|
| Identical to the GT | 1.0 | 1 / 1 / 1 | |
| Same table, written as a markdown pipe table | 1.0 | 1 / 1 / 1 | The pipe table is converted to HTML before comparison. |
| `5,5%` read as `5.5%` | 0.9643 | 1 / 1 / 1 | The cell is off by 1 of 4 characters, cost 0.25. TEDS = 1 - 0.25/7. |
| `6 tháng` read as `6 thang` | 0.9796 | 1 / 1 / 1 | The cell is off by 1 of 7 characters. |
| One extra row | 0.7 | 1 / 1 / 1 | 3 nodes added. The larger tree has 10 nodes, TEDS = 1 - 3/10. |
| One extra empty column | 0.7778 | 1 / 1 / 1 | 2 cells added. The larger tree has 9 nodes, TEDS = 1 - 2/9. |
| First row merged into 1 cell with `colspan=2` | 0.7143 | 1 / 1 / 1 | Different span and one cell missing. |
| **Table split into 2 pieces** | 0.5714 | 1 / 1 / **2** | Only the best-matching piece is paired; the other piece does not affect TEDS. |
| Pred has no table | n/a | **0** / 1 / 0 | A missed table does not lower TEDS, it only shows in the count columns. |
| GT has no table, pred has 1 | n/a | 0 / 0 / **1** | An extra table also only shows in the count columns. |

#### Reading the results

- **There is no raw mode** (principle C7), so WER is lower than under the usual scoring.
- **The whole document is scored at once.** Every reading-order difference (a header or footer repeated on each page, a table placed elsewhere) becomes deletions plus insertions.
- **Insertions have no ceiling, omissions are capped at 1.0.** WER > 1 is possible. A high WER does not always mean the engine misread; check whether the pred is longer or shorter than the GT.
- **Text read from an image is only skipped when the GT has a `<!-- image -->` marker at that position.** Without a marker, an image description written as an ordinary sentence (for example chandra writing *"The screenshot shows the Confluence CMS interface..."*) and text copied from a screenshot are both insertion errors. Only the two `269_...` files have markers so far (20 and 30 markers). The four contract files have none yet.
- **Always read WER next to the `ignored` column.** A marker also skips text the engine invented right next to the image. An `ignored` value that is unusually large for the size of the images in the source document is a sign the marker is skipping too much.
- **Image text placed in the wrong position is still counted as errors.** If the engine puts the image text after the next paragraph, the marker cannot skip all of it (see the WER example).
- **TEDS does not penalize extra or missing tables.** Always read TEDS with `matched / n_gold / n_pred`. For example chandra on `269_...-24-46` has TEDS 0.9456, but emits 25 tables against 14 in the GT, and only 13 are paired.
- **Table pairing is greedy with a 0.5 threshold.** A table piece with a structure score < 0.5 is not paired, and the pairing is not guaranteed to be globally optimal.
- **Text in table cells is scored twice**: once in WER (tags replaced by spaces), once in TEDS. In TEDS the cell text does not go through tone-mark normalization, so `hoà` differs from `hòa`.
- **The characters `_`, `*`, `` ` `` are always removed**, even when they are real content, for example a `______` fill-in line.
- **One wrong punctuation mark or tone mark makes the whole word wrong** in WER. Case and number formatting are not normalized.
- **TEDS has a floor of 0**, never negative.

### Extraction & Structure

### Các metrics khác có thể dùng thêm

| Metric | Ý nghĩa (khía cạnh khác) | Khi nào nên dùng |
|---|---|---|
| **Region classification accuracy** | Phân loại vùng (text/table/stamp…) đúng bao nhiêu %, so với `blocks[].type` | Khi tầng sau xử lý khác nhau theo loại vùng (ví dụ vùng bảng được đưa vào bước dựng bảng riêng) |
| **Reading order accuracy** (Kendall's tau hoặc edit distance trên chuỗi thứ tự) | Thứ tự đọc có giống người đọc không, so với `blocks[].order` | Tài liệu nhiều cột hoặc bố cục phức tạp, nhất là khi output OCR được đưa vào RAG |
| **Confidence calibration (ECE)** | Độ tin cậy model báo ra có khớp với tỷ lệ đúng thật không | Khi dùng confidence để quyết định chuyển người kiểm tra (human review) |
| **Latency / Cost per page, Throughput** | Thời gian và chi phí xử lý mỗi trang, số trang/phút | Luôn nên báo cáo kèm, để so sánh giữa các giải pháp |
