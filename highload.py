import asyncio
import logging
import time

from pytoniq import LiteBalancer
from pytoniq import WalletV4R2, Address
from pytoniq import begin_cell, Cell
from pytoniq.contract.wallets.highload import HighloadWallet
from pytoniq.contract.utils import generate_query_id
from pytoniq_core.crypto.keys import mnemonic_new, mnemonic_is_valid


logging.basicConfig(filename=None,  # path to log file, None -> console
                    format='%(message)s',
                    level=logging.WARNING)


logging.getLogger("root").setLevel(logging.INFO)
logging.getLogger("LiteBalancer").setLevel(logging.WARNING)
logging.getLogger("LiteClient").setLevel(logging.WARNING)


TRANSACTION_COST = 0.0035
FORWARD_TON_AMOUTN = 0
RECIPIENT_ADDRESS = Address("EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c")


async def main():
    tick = input("enter tick (nano, gram, bolt etc.): ")
    decimals = int(input("enter token decimals (usually 9): "))
    limit_per_mint = int(input("enter limit per mint: "))
    total_transactions = int(input("Enter the number of transactions to send: "))

    amount = str(limit_per_mint * (10 ** decimals))
    comment_text = "data:application/json,{\"p\":\"ton-20\",\"op\":\"mint\",\"tick\":\"" + tick + "\",\"amt\":\"" + amount + "\"}"
    payload = begin_cell().store_uint(0, 32).store_snake_string(comment_text).end_cell()

    wallet_mnemonic = input("Insert your seed phrase or press Enter to generate new one: ").split()
    print()
    if not wallet_mnemonic:
        wallet_mnemonic = mnemonic_new()
        logging.warning(f'Your new wallet mnemonic is: {" ".join(wallet_mnemonic)}\n')
    elif not mnemonic_is_valid(wallet_mnemonic):
        logging.error("Invalid seed phrase")
        exit(-1)

    client = LiteBalancer.from_mainnet_config(trust_level=1)
    await client.start_up()
    wallet = await HighloadWallet.from_mnemonic(client, wallet_mnemonic)
    wallet_balance = await wallet.get_balance()
    
    logging.info(f"Your highload wallet address: {wallet.address.to_str(is_bounceable=False)}")
    logging.info(f"Balance: {wallet_balance / 10 ** 9}")
    
    RECIPIENT_ADDRESS = wallet.address  # new standart ¯\_(ツ)_/¯

    all_fees = (total_transactions * TRANSACTION_COST + 0.017) * 10 ** 9
    if wallet_balance < all_fees:
        input("your balance is insufficient, press enter after you top up your wallet"
              f" (need minimum {all_fees / 10 ** 9} TON) ")
        try:
            await client.get_time()
        except Exception:
            await client.start_up()
    
    wallet_balance = await wallet.get_balance()
    if wallet_balance < all_fees:
        logging.error(f"Still insufficient balance ({wallet_balance / 10 ** 9} < {all_fees / 10 ** 9}) :(")
        exit(-1)

    if not (await check_deployed(wallet)):
        exit(-1)

    start_time = int(time.time())

    successfull_txs = 0
    for i in range(total_transactions // 254):
        res = await send_wait_transaction(wallet, RECIPIENT_ADDRESS, FORWARD_TON_AMOUTN, payload, 254)
        if not res:
            logging.error(f"Failed to send tansfer №{i}")
        else:
            successfull_txs += 254
            logging.info(f"{i} successful transfer ({successfull_txs} transactions)")
    
    if total_transactions % 254 != 0:
        res = await send_wait_transaction(wallet, RECIPIENT_ADDRESS, FORWARD_TON_AMOUTN, payload, total_transactions % 254)
        if not res:
            logging.error(f"Failed to send tansfer №{total_transactions // 254 + 1}")
        else:
            successfull_txs += total_transactions % 254
            logging.info(f"{total_transactions // 254 + 1} successful transfer ({successfull_txs} transactions)")

    spent_time = int(time.time()) - start_time

    await client.close_all()
    logging.info(f"total successfull transactions: {successfull_txs}\n"
                 f"time spent: {spent_time // 3600 :02d}:{(spent_time % 3600) // 60:02d}:{(spent_time % 60):02d}")
    


async def check_deployed(wallet: HighloadWallet):
    account_state = await wallet.get_account_state()
    if account_state.state.type_ == "uninitialized":
        balance = await wallet.get_balance()
        if balance < 0.006 * 10 ** 9:
            logging.error("Can't deploy wallet: need at least 0.006 TON on balance")
            return False
        logging.warning("Wallet is not initialized, trying to deploy wallet")
        for i in range(3):
            logging.info(f"Try №{i}")
            await wallet.deploy_via_external()
            for _ in range(60):  # wait for 5 minutes
                account_state = await wallet.get_account_state()
                if account_state.state.type_ != "uninitialized":
                    logging.info("Wallet is successfully deployed")
                    return True
                await asyncio.sleep(5)
        logging.error("Failed to deploy wallet :(")
        return False
    
    return True


async def send_wait_transaction(wallet: HighloadWallet, address: Address | str, 
                                send_amount: int, payload: Cell, msg_count: int = 254):
    msgs = []
    for _ in range(msg_count):
        msgs.append(wallet.create_wallet_internal_message(address, 3, send_amount, payload))
    query_id = generate_query_id()
    await wallet.raw_transfer(msgs, query_id=query_id)

    for _ in range(6 * 5):  # wait 5 minutes for transaction
        is_processed = await wallet.processed(query_id)
        if is_processed:
            return True
        await asyncio.sleep(10)

    return False


if __name__ == "__main__":
    asyncio.run(main())
           