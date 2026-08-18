"""Fine-tune Tesseract LSTM on LPBank line crops from orchestrate artifacts.

Pipeline:

``python -m finetune cut``       crop TextLine images from pages/*.json + images/
``python -m finetune align``     write .gt.txt by aligning OCR to ground_truth/
``python -m finetune lstmf``     encode png+gt.txt into .lstmf + list.train
``python -m finetune train``     lstmtraining -> vie_lpbank.traineddata

Or run them in order with ``python -m finetune pipeline``.
"""
