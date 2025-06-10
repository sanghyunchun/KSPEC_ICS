import os
import shutil


base_dir = os.path.dirname(os.path.abspath(__file__))
grab_save_path = os.path.join(base_dir, "img", "GFA_data")


file_list = sorted([
    f for f in os.listdir(grab_save_path)
    if os.path.isfile(os.path.join(grab_save_path,f))
])

print(file_list)
