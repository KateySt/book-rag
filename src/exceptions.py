class BookRagError(Exception):
    pass


class DocumentParseError(BookRagError):
    pass


class ObjectMissingError(BookRagError):
    pass


class ObjectTooLargeError(BookRagError):
    pass


class RunSupersededError(BookRagError):
    pass


class UnsupportedFileError(BookRagError):
    pass


class QueueFullError(BookRagError):
    pass
