import asyncio
import aiohttp
import time

time_timeout = 200

# total  整个操作的最大秒数，包括建立连接、发送请求和读取响应。
# connect  如果超出池连接限制，则建立新连接或等待池中的空闲连接的最大秒数。
# sock_connect  为新连接连接到对等点的最大秒数，不是从池中给出的。
# sock_read  从对等点读取新数据部分之间允许的最大秒数。

local_addr = ('0.0.0.0', 60380)

client_timeout = aiohttp.ClientTimeout(
    total = time_timeout,
    sock_read = time_timeout
)

netctlpan_url = "http://15.165.13.221:60823/netctlpan"

payload = {
    'input_filename': 'minio://molly/c709d1d3-e626-4717-aeda-fdcc38367609_20倍_jj小批量.fasta', 
    'mhc_allele': 'HLA-A32:01,HLA-B07:02,HLA-B44:03,HLA-C04:01,HLA-C07:02', 
    'weight_of_clevage': 0.225, 
    'weight_of_tap': 0.025, 
    'peptide_length': '8,9,10,11', 
    'epi_threshold': 1.0, 
    'output_threshold': -99.9, 
    'sort_by': -1, 
    'num_workers': 20, 
    'mode': 1, 
    'hla_mode': 1, 
    'peptide_duplication_mode': 1
}

async def call_netctlpan():

#    connector = aiohttp.TCPConnector(
#        local_addr = local_addr,
#        keepalive_timeout = time_timeout,
#        enable_cleanup_closed = True,
#    )

    for retry in range(10):
        connector = aiohttp.TCPConnector(
            local_addr = local_addr,
            keepalive_timeout = time_timeout,
            enable_cleanup_closed = True,
        )
        try:
            async with aiohttp.ClientSession(connector=connector,timeout=client_timeout) as session:
                async with session.post(netctlpan_url, timeout=client_timeout, json=payload) as response:
                    response.raise_for_status()
                    result = await response.json()
                    connector.close()
                    return result
        except Exception as e:
            print("发生异常类型：", type(e).__name__)
            print("异常信息：", str(e))
            time.sleep(20)

async def main():

    """主函数示例"""
    result = await call_netctlpan()
    print(result)
    if result:
        print("API调用成功，结果:", result)
    else:
        print("API调用失败")

if __name__ == "__main__":
    asyncio.run(main())
    time.sleep(5)
