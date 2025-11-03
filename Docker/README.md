# Docker Setup for MealAgent

This directory contains Docker Compose configuration for running Weaviate locally for MealAgent development.

## Services

### Weaviate

- **Image**: `cr.weaviate.io/semitechnologies/weaviate:1.32.8`
- **HTTP Port**: `8078` (mapped from container port 8080)
- **gRPC Port**: `50051`
- **Vectorizer Module**: `text2vec-transformers` (Qwen Qwen3-Embedding-0.6B)
- **Data Persistence**: Volume `weaviate_data_v2` mounted at `/var/lib/weaviate`

### Transformers Inference (t2v)
- **Image**: `semitechnologies/transformers-inference:qwen-qwen3-embedding-0.6b`
- **Port**: `9000` (optional, for health checks)
- **GPU**: Uses NVIDIA GPU if available (CUDA enabled)

## Usage

### Start Services

```bash
cd Docker
docker-compose up -d
```

### Stop Services
```bash
docker-compose down
```

### Stop and Remove Volumes (⚠️ Deletes all data)
```bash
docker-compose down -v
```

### View Logs
```bash
docker-compose logs -f weaviate
docker-compose logs -f t2v
```

### Check Weaviate Health

```bash
curl http://localhost:8078/v1/.well-known/ready
```

## Configuration for MealAgent

When using the MealAgent migration scripts, use these connection parameters:


- **Host**: `localhost`
- **HTTP Port**: `8078`
- **gRPC Port**: `50051`

Example:
```bash
python elysia/elysia/MealAgent/migrations/create_collections.py --create --host localhost --port 8078 --grpc-port 50051
```

## Environment Variables

Key Weaviate settings:
- `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED`: `true` (dev only - disable in production)
- `ENABLE_MODULES`: `text2vec-transformers`
- `DEFAULT_VECTORIZER_MODULE`: `none` (use named vectors per collection)
- `QUERY_MAXIMUM_RESULTS`: `100000`
- `ASYNC_INDEXING`: `true` (for better performance)

## Production Considerations

For production deployment:
1. **Disable anonymous access**: Set `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "false"`
2. **Add API key**: Configure `AUTHENTICATION_APIKEY_ALLOWED_KEYS` and `AUTHENTICATION_APIKEY_USERS`
3. **Use HTTPS**: Configure TLS certificates
4. **Use cloud or managed service**: Consider Weaviate Cloud or K8s deployment
5. **Scale transformers service**: Use multiple replicas for higher throughput

## Troubleshooting

### Weaviate won't start
- Check if ports 8078/50051 are already in use: `netstat -an | findstr "8078\|50051"`
- Check logs: `docker-compose logs weaviate`

### GPU not detected
- Install NVIDIA Docker runtime: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide/
- Verify: `docker run --rm --gpus all nvidia/cuda:11.0.3-base-ubuntu20.04 nvidia-smi`

### Out of memory
- Reduce `QUERY_MAXIMUM_RESULTS` or add more memory to Docker
- Consider using CPU-only transformers model for smaller instances

