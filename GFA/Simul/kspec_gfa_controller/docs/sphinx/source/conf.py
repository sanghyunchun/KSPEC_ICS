# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

sys.path.insert(0, os.path.abspath("/home/kspec/mingyeong/kspec_gfa_controller/controller/src"))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "kspec-gfa"
copyright = "2024, mingyeong"
author = "Mingyeong Yang"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

# Add Napoleon extension
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',  # Add this line
    # ... other extensions
]

templates_path = ["_templates"]
exclude_patterns = []

# Napoleon settings (optional)
napoleon_google_docstring = False
napoleon_numpy_docstring = True

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# html_theme = "sphinx_rtd_theme"

# on_rtd is whether we are on readthedocs.org,
# this line of code grabbed from docs.readthedocs.org
# on_rtd = os.environ.get('READTHEDOCS', None) == 'True'
# only import and set the theme if we're building docs locally
# if not on_rtd:
#    import sphinx_rtd_theme
#    html_theme = 'sphinx_rtd_theme'
#    html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]

html_static_path = ["_static"]
html_logo = "_static/KSPEC_FIN_6_white_color.png"
html_title = "KSPEC-GFA"
