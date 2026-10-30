# GeoNames offline snapshot

Source: https://download.geonames.org/export/dump/US.zip
Documentation: https://download.geonames.org/export/dump/readme.txt
Attribution: GeoNames, https://www.geonames.org/, CC BY 4.0.

`US.zip` is the frozen US country extract. `snapshot.json` records its URL and SHA-256.
`readme.txt` preserves GeoNames format and license documentation. `places.sqlite` is an
ignored, rebuildable name index covering feature classes A, P and S. Country ZIPs stay
unchanged on repeated runs; matching is offline after initial download.

Call `prepare_geonames(["US"])` from the notebook. Add other uppercase country codes
when sources require them. Missing country ZIPs are downloaded once. To retry a processed fact with new matching decisions, reset its location status to
undefined and clear its coordinates. Coordinates are GeoNames
place points and do not verify historical event sites.
