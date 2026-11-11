# Measurements

One run of `node tests/measure.js dist/berthline-linux` on a modest laptop (Intel Core i3-10110U,
8 GB RAM, Fedora 45), 0.3.0 package. Each profile opens its sample project once to warm the disk
cache, then again for the numbers. Memory is the whole process tree after 30 seconds idle, counted
as PSS so shared pages are not counted twice. Web Wherry includes its preview, which opens by itself.

| Profile | Startup | Memory (PSS) | Processes | Extensions on disk |
|---|---:|---:|---:|---:|
| Bean Barge | 4.0 s | 1212 MB | 11 | 267 MB |
| Web Wherry | 3.0 s | 811 MB | 13 | 27 MB |
| Standard Sloop | 5.7 s | 731 MB | 10 | 0 MB |

The unpacked package takes 1.5 GB; the editor, Node.js and the Hub (1.06 GB of it) are shared by all
profiles. Bean Barge's extensions include their own Java runtime.

Run the script again after a change to compare.
