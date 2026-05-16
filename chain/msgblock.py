import hashlib
import jsonpickle
from datetime import datetime


class MsgBlock:
    def __init__(self, index, miner, proof, prev_hash, msg):
        self.index = index
        self.miner = miner
        self.timestamp = datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
        self.proof = proof
        self.prev_hash = prev_hash
        self.msg = msg

    @property
    def hash(self):
        block_str = str(self)
        return hashlib.sha256(block_str.encode()).hexdigest()

    def __str__(self):
        return jsonpickle.encode(self)

    def __repr__(self):
        return str(self)
