import jsonpickle


class Transaction:
    def __init__(self, to, msg):
        self.to = to
        self.msg = msg

    def __str__(self):
        return jsonpickle.encode(self)

    def __repr__(self):
        return str(self)
