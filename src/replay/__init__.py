"""Phase 3: freeze the versions, photograph the artifacts, rehearse the replay.

Three modules, and the split is by who owns the fact:

* :mod:`src.replay.freeze` reads every version the replay is frozen against
  **from its producer** and refuses a document that disagrees with them;
* :mod:`src.replay.cutoff` owns the cutoff rule and the post-cutoff queue, so
  a date that was left out of the batch is observably queued rather than
  observably absent;
* :mod:`src.replay.snapshot` photographs the artifacts of both repositories
  with their checksums, recording what it could not measure instead of
  omitting it.

Nothing here reads Earth Engine, an object store, the network, or a clock
unless a caller hands it the value.
"""
