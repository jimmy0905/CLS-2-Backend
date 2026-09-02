# The digest is intentionally pinned.  Release CI resolves and records its
# replacement digest in deployment/images.lock.json before publishing bundles.
FROM cubejs/cube:v1.7.26@sha256:51d467b223492da5c35139c31760c5329e770028bbe6cb4faa590400e5445941

WORKDIR /cube/conf
COPY cube.js ./cube.js
COPY lib ./lib
COPY model ./model
COPY multitenant ./multitenant
