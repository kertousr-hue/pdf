# Double-cliquez sur ce fichier pour lancer PDF Éditeur sous Windows (sans fenêtre de console).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_editeur import main  # noqa: E402

main()
