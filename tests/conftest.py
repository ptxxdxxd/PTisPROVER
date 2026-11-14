from __future__ import annotations

import os

from hypothesis import settings

# "ci" is derandomized so a failure on CI reproduces locally with the same profile.
settings.register_profile("ci", derandomize=True, max_examples=500, deadline=None)
settings.register_profile("dev", max_examples=200, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
