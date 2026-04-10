# goodc-assets

Static catalog image hosting for GoodCigars via GitHub Pages.

Generated assets live under `catalog/` using tokenized filenames:

`b####-s####.<ext>`

The tokenizer reads the main app fixture from:

`/Users/dm/Documents/Projects/GoodCigars/GoodCigarsApp/Resources/CatalogFixtures/goodcigarscatalog.json`

After publishing, image URLs are available at:

`https://integrationuser92.github.io/goodc-assets/catalog/b####-s####.<ext>`

Hosted catalog metadata is published from the app fixture to:

- `catalog.json`
- `catalog-index.json`

Useful scripts:

- `scripts/rotate_catalog_images.py`: rotate landscape catalog assets clockwise and validate portrait output.
- `scripts/publish_catalog_metadata.py`: publish `catalog.json` and `catalog-index.json` from the app fixture.
