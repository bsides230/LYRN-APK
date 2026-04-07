from PIL import Image
import os

try:
    # Define paths
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    jpg_path = os.path.join(SCRIPT_DIR, "images", "lyrn_logo.jpg")
    ico_path = os.path.join(SCRIPT_DIR, "images", "favicon.ico")

    # Open the JPEG image
    img = Image.open(jpg_path)

    # To create a good quality ICO, it's best to provide multiple sizes.
    # Let's provide a few common ones.
    icon_sizes = [(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)]

    # Save as ICO
    img.save(ico_path, format='ICO', sizes=icon_sizes)

    print(f"Successfully converted {jpg_path} to {ico_path}")

except Exception as e:
    print(f"An error occurred: {e}")
