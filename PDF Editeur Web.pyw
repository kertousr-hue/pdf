# Double-cliquez pour lancer PDF Éditeur dans le navigateur (version web, sans fenêtre de console).
# Pour quitter : menu Fichier > Quitter PDF Éditeur.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_web import main  # noqa: E402

main()
