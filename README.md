# JSON-RPC Cache Proxy

This project provides a caching proxy for JSON-RPC requests using Nginx and Lua. It's designed to reduce the load on blockchain RPC nodes by caching responses for a configurable amount of time.

## Features

- Supports multiple blockchain RPC endpoints
- Configurable cache duration for each endpoint
- Detailed logging for easy debugging

## Prerequisites

- Docker

## Quick Start

1. Clone this repository:
   ```
   git clone https://github.com/sourcapital/json-rpc-cache-proxy.git
   cd json-rpc-cache-proxy
   ```

2. Build the Docker image:
   ```
   docker build -t json-rpc-cache-proxy .
   ```

3. Run the container:
   ```
   docker run -d -p 8080:80 \
     -e RPC_NODE_ETHEREUM=https://mainnet.infura.io/v3/YOUR_API_KEY \
     -e RPC_NODE_ARBITRUM=https://arbitrum-mainnet.infura.io/v3/YOUR_API_KEY \
     -e RPC_NODE_SOLANA=https://mainnet.helius-rpc.com/?api-key=YOUR_API_KEY \
     -e CACHE_TIME_ETHEREUM=5 \
     -e CACHE_TIME_ARBITRUM=5 \
     -e CACHE_TIME_SOLANA=5 \
     --name json-rpc-cache-proxy \
     json-rpc-cache-proxy
   ```

   Replace `YOUR_API_KEY` with your actual API keys.

4. The proxy is now running and accessible at `http://localhost:8080`.

## Configuration

### Environment Variables

- `RPC_NODE_<CHAIN>`: The URL of the RPC node for a specific blockchain. Replace `<CHAIN>` with the blockchain name (e.g., ETHEREUM, ARBITRUM, SOLANA).
- `CACHE_TIME_<CHAIN>`: The cache duration in seconds for a specific blockchain. If not set, it defaults to 10 seconds.

### Endpoint Names

The endpoint names used in the proxy are automatically generated from the environment variable names. The proxy removes the `RPC_NODE_` prefix and converts the remaining part to lowercase. For example:

- `RPC_NODE_ETHEREUM` becomes `/ethereum`
- `RPC_NODE_ARBITRUM` becomes `/arbitrum`
- `RPC_NODE_SOLANA` becomes `/solana`

These generated names are used as the path in your requests to the proxy.

### Adding New Chains

To add a new blockchain RPC endpoint, simply add new environment variables following the pattern above. For example:

```
-e RPC_NODE_NEWCHAIN_TESTNET=https://rpc.newchain.com
-e CACHE_TIME_NEWCHAIN_TESTNET=30
```

This would create a new endpoint accessible at `/newchain_testnet`.

## Usage

Once the proxy is running, you can send JSON-RPC requests to it using the generated endpoint names. The proxy will cache the responses and serve cached responses when possible.

Example using curl:

```bash
curl -X POST http://localhost:8080/ethereum \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
```

Replace `/ethereum` with the appropriate chain name as generated from your environment variables.

## Debugging

The proxy adds some headers to the response to help with debugging:

- `X-Cache-Status`: Indicates whether the response was a cache hit or miss.
- `X-Cache-Key`: The key used for caching the response.

You can view these headers in the response or check the Docker logs for more detailed information:

```
docker logs json-rpc-cache-proxy
```

## License

```
MIT License

Copyright (c) 2024 Sour Capital Pte. Ltd.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
