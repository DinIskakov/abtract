# demo_site

`v0/` is the fake "Zephyr Compute" serverless-GPU marketing + docs site with deliberate agent traps
(see `TRAPS.md`); `tasks.json` is the list of `Task`s the swarm runs against it.

To look at it locally (no build step, no external assets):

    cd demo_site/v0 && python3 -m http.server 9000

then open http://localhost:9000/ . Form posts go to `api/...` relative endpoints, which the plain
http.server returns 501 for; the real hosting server (`abtract/hosting`) records them as SiteEvents
and redirects to `thanks.html`. Clear `localStorage` (or use a private window) to see the cookie wall again.
