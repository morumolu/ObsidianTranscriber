from enum import Enum


class ModelSize(str, Enum):
    tiny = "tiny"
    base = "base"
    small = "small"
    medium = "medium"
    large_v1 = "large-v1"
    large_v2 = "large-v2"
    large_v3 = "large-v3"
    large_v3_turbo = "large-v3-turbo"
    distil_large_v3 = "distil-large-v3"