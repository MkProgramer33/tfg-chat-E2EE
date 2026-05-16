from argparse import ArgumentParser
from flask import Flask, request
from blockchain import Blockchain
from threading import Thread
from transaction import Transaction
import time
import jsonpickle
from uuid import uuid4

app = Flask(__name__)

parser = ArgumentParser()
parser.add_argument('-p', '--port', default=8000, type=int, required=True)
parser.add_argument('-m', '--mine', action='store_true')
parser.add_argument('-b', '--boot-node', default=None, type=str)
parser.add_argument('-i', '--node-id', default=str(uuid4()).split('-')[0], type=str)
parser.add_argument('-n', '--node-ip', default='localhost', type=str)
args = parser.parse_args()

# Bulletin-board genesis: no balances, just an empty genesis block.
blockchain = Blockchain(args.node_id, [], f"{args.node_ip}:{args.port}", boot_node=args.boot_node)
print('Input config', args)


def mining_loop():
    while True:
        blockchain.mine()
        time.sleep(1)


def resolve_split_loop():
    while True:
        blockchain.resolve_split()
        time.sleep(10)


def gossip_loop():
    while True:
        blockchain.gossip_peerstore()
        time.sleep(10)


if args.mine:
    Thread(target=mining_loop, daemon=True).start()
    Thread(target=resolve_split_loop, daemon=True).start()
    Thread(target=gossip_loop, daemon=True).start()

Thread(target=app.run, args=('0.0.0.0', args.port)).start()


@app.route('/', methods=['GET'])
def index():
    return (
        f"Node_Id: {blockchain.node_id}\n"
        f"Mempool: {blockchain.mempool}\n"
        f"Peerstore: {blockchain.peerstore}\n"
        f"MsgBlock: {blockchain.blocks}"
    ), 200


# POST localhost:5000/addtx  body: {"sender": "...", "to": "...", "msg": "<ciphertext>"}
@app.route('/addtx', methods=['POST'])
def addtx():
    payload = request.get_json(silent=True) or {}
    sender = payload.get('sender')
    to = payload.get('to')
    msg = payload.get('msg')

    if not sender or not to or not msg:
        return "Fields can't be empty", 400
    try:
        tx = blockchain.new_transaction(sender, to, msg)
    except Exception as e:
        return f"Error adding new tx: {e}", 500
    return f"Added tx to the pool: {tx}", 200


# POST localhost:5000/addblock  body: {"block": "<jsonpickle>"}
@app.route('/addblock', methods=['POST'])
def addblock():
    payload = request.get_json(silent=True) or {}
    block_serialized = payload.get('block')
    if not block_serialized:
        return "MsgBlock field can't be empty", 400

    block = jsonpickle.decode(block_serialized)
    blockchain.add_block(block)
    return f"Added block to the blockchain: {block}", 200


# localhost:5000/addpeer?peer=localhost:5001
@app.route('/addpeer', methods=['GET'])
def addpeer():
    peer = request.args.get('peer')
    if not peer:
        return "Peer field can't be empty", 500
    blockchain.add_peer(peer)
    return f"Added peer: {peer}", 200


# localhost:5000/getlastblock
@app.route('/getlastblock', methods=['GET'])
def getlastblock():
    return str(blockchain.blocks[-1]), 200


# localhost:5000/getblockchain
@app.route('/getblockchain', methods=['GET'])
def getblockchain():
    return str(jsonpickle.encode(blockchain.blocks)), 200


# localhost:5000/getpeerstore
@app.route('/getpeerstore', methods=['GET'])
def getpeerstore():
    return str(blockchain.peerstore), 200


# localhost:5000/getmempool
@app.route('/getmempool', methods=['GET'])
def getmempool():
    return str(blockchain.mempool), 200


# localhost:5000/mine — minado manual (debug)
@app.route('/mine', methods=['GET'])
def mine():
    block = blockchain.mine()
    if block is None:
        return "Nothing to mine: mempool is empty", 200
    return f"Done mining, the proof is {str(block)}", 200


# localhost:5000/resolvesplit — fuerza la resolución de un fork
@app.route('/resolvesplit', methods=['GET'])
def resolvesplit():
    blockchain.resolve_split()
    return "Done", 200
