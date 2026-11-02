class OrmRuntimeError(Exception):
    """Validation or policy failure before or during a typed ORM read."""


class SchemaNotReadError(OrmRuntimeError):
    """A model was queried before its fields were read in the current request."""

    def __init__(self, model: str):
        super().__init__(
            f"fields of {model} not read yet: call fields_get on {model} without field_names, "
            "then filter or group on every qualifier of the question (type, status, party, period) "
            "using the fields it lists."
        )
        self.model = model
