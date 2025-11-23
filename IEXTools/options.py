from enum import Enum

FeedTypeTops = "TOPS"
FeedTypeDpls = "DPLS"
FeedTypeDeep = "DEEP"


class FileTypeOptions(str, Enum):
    TOPS = FeedTypeTops
    DEEP = FeedTypeDeep
    DPLS = FeedTypeDpls