import os
import logging
from typing import List, Optional, Any, Dict, Callable, ClassVar
from functools import lru_cache
from dotenv import load_dotenv
import concurrent.futures
import time
from threading import Lock

from openai import OpenAI
import numpy as np

from lancedb.embeddings import TextEmbeddingFunction, EmbeddingFunctionRegistry
from pydantic import Field
import voyageai
import tiktoken
from pathlib import Path

root_dir = str(Path(os.path.dirname(os.path.abspath(__file__))).parent)
env_path = os.path.join(root_dir, '.env')
load_dotenv(env_path)


# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OpenAIEmbeddings(TextEmbeddingFunction):
    """
    OpenAI嵌入向量生成器，支持多线程并行请求
    """
    model_name: str = Field(default="text-embedding-3-large", description="Embedding model name")
    api_key: Optional[str] = Field(default=None, description="Embedding API key")
    
    # 类级别的配置参数 - 使用ClassVar标注
    max_tokens: ClassVar[int] = 8000
    max_tokens_per_batch: ClassVar[int] = 300000
    model: ClassVar[str] = "text-embedding-3-large"
    max_texts_per_batch: ClassVar[int] = 1000
    thread_count: ClassVar[int] = 20
    retry_count: ClassVar[int] = 3
    retry_delay: ClassVar[float] = 1.0
    
    # 缓存维度值作为类变量
    _ndims_cache: ClassVar[Optional[int]] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 仅初始化必要的API配置
        self.api_key = os.getenv("EMBEDDING_API_KEY")
        self.model_name = self.model
        
        if not self.api_key:
            logger.warning("未找到API密钥，请确保设置了EMBEDDING_API_KEY环境变量")
        
        logger.info(f"OpenAIEmbeddings初始化完成: 模型={self.model_name}")

    
    def generate_embeddings(self, texts) -> List[List[float]]:
        """使用多线程处理大量文本"""
        if isinstance(texts, str):
            texts = [texts]
            
        # 单个文本直接处理
        if len(texts) <= 1:
            client = self._embedding_client()
            response = client.embeddings.create(
                model=self.model_name,
                input=texts,
                encoding_format="float"
            )
            return [data.embedding for data in response.data]
            
        # 创建批次，并记录每个批次所对应的原始索引
        batches = []
        batch_indices = []  # 记录每个批次中文本的原始索引
        
        tokenizer = OpenAIEmbeddingTokenizer()
        current_batch = []
        current_indices = []  # 当前批次的索引
        current_token_count = 0
        
        for i, text in enumerate(texts):
            text_token_count = tokenizer.get_token_count(text)
            
            # 如果当前文本会导致批次超过限制，则创建新批次
            if (current_token_count + text_token_count > self.max_tokens_per_batch or 
                len(current_batch) >= self.max_texts_per_batch):
                if current_batch:  # 避免创建空批次
                    batches.append(current_batch)
                    batch_indices.append(current_indices)
                    current_batch = []
                    current_indices = []
                    current_token_count = 0
            
            # 添加文本到当前批次
            current_batch.append(text)
            current_indices.append(i)  # 记录原始索引
            current_token_count += text_token_count
        
        # 添加最后一个批次
        if current_batch:
            batches.append(current_batch)
            batch_indices.append(current_indices)
        
        total_batches = len(batches)
        logger.info(f"总文本数: {len(texts)}，分为 {total_batches} 个批次，使用 {self.thread_count} 个线程处理")
        
        # 预分配结果数组，确保顺序正确
        all_embeddings = [None] * len(texts)
        
        # 用于统计的局部变量
        total_requests = 0
        successful_requests = 0
        failed_requests = 0
        
        def process_batch(batch_idx, batch, indices):
            """内部函数处理单个批次，返回嵌入向量和对应的原始索引"""
            nonlocal total_requests, successful_requests, failed_requests
            
            for attempt in range(self.retry_count):
                try:
                    total_requests += 1
                    client = self._embedding_client()
                    
                    start_time = time.time()
                    response = client.embeddings.create(
                        model=self.model_name,
                        input=batch,
                        encoding_format="float"
                    )
                    elapsed_time = time.time() - start_time
                    
                    successful_requests += 1
                    batch_embeddings = [data.embedding for data in response.data]
                    logger.info(f"批次 {batch_idx+1}/{total_batches} 处理完成，耗时 {elapsed_time:.2f} 秒")
                    
                    # 返回嵌入向量和对应的原始索引
                    return batch_embeddings, indices
                except Exception as e:
                    failed_requests += 1
                    if attempt < self.retry_count - 1:
                        logger.warning(f"批次 {batch_idx+1}/{total_batches} 处理失败 (尝试 {attempt+1}/{self.retry_count}): {str(e)}，将在 {self.retry_delay} 秒后重试")
                        time.sleep(self.retry_delay)
                    else:
                        logger.error(f"批次 {batch_idx+1}/{total_batches} 最终失败: {str(e)}")
                        raise
        
        # 使用ThreadPool处理批次
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_count) as executor:
            # 提交所有批次任务
            future_to_batch_idx = {
                executor.submit(process_batch, i, batch, indices): i 
                for i, (batch, indices) in enumerate(zip(batches, batch_indices))
            }
            
            # 处理结果
            for future in concurrent.futures.as_completed(future_to_batch_idx):
                batch_idx = future_to_batch_idx[future]
                try:
                    batch_embeddings, indices = future.result()
                    
                    # 将结果放入对应的位置，确保顺序正确
                    for embed, orig_idx in zip(batch_embeddings, indices):
                        all_embeddings[orig_idx] = embed
                        
                except Exception as e:
                    logger.error(f"批次 {batch_idx+1}/{total_batches} 处理失败: {str(e)}")
        
        # 检查是否有未完成的嵌入
        if None in all_embeddings:
            missing_indices = [i for i, e in enumerate(all_embeddings) if e is None]
            logger.warning(f"有 {len(missing_indices)} 个文本未能生成嵌入向量")
            
            # 可以在这里添加单独处理未完成文本的逻辑
            for i in missing_indices:
                try:
                    client = self._embedding_client()
                    response = client.embeddings.create(
                        model=self.model_name,
                        input=[texts[i]],
                        encoding_format="float"
                    )
                    all_embeddings[i] = response.data[0].embedding
                    logger.info(f"单独处理文本 {i} 成功")
                except Exception as e:
                    logger.error(f"单独处理文本 {i} 失败: {str(e)}")
                    # 如果仍然失败，填充一个零向量避免程序崩溃
                    if self._ndims_cache:
                        all_embeddings[i] = [0.0] * self._ndims_cache
        
        logger.info(f"嵌入处理完成。总请求: {total_requests}, 成功: {successful_requests}, 失败: {failed_requests}")
        
        return all_embeddings
    
    def _create_batches(self, texts) -> List[List[str]]:
        """根据token数和文本数量创建批次"""
        batches = []
        current_batch = []
        current_token_count = 0
        
        tokenizer = OpenAIEmbeddingTokenizer()
        
        for text in texts:
            text_token_count = tokenizer.get_token_count(text)
            
            # 如果当前文本会导致批次超过限制，则创建新批次
            if (current_token_count + text_token_count > self.max_tokens_per_batch or 
                len(current_batch) >= self.max_texts_per_batch):
                if current_batch:  # 避免创建空批次
                    batches.append(current_batch)
                    current_batch = []
                    current_token_count = 0
            
            # 添加文本到当前批次
            current_batch.append(text)
            current_token_count += text_token_count
        
        # 添加最后一个批次
        if current_batch:
            batches.append(current_batch)
        
        return batches

    def ndims(self) -> int:
        """
        返回嵌入向量的维度，使用类缓存
        """
        if OpenAIEmbeddings._ndims_cache is None:
            # 为单个文本生成嵌入向量并缓存维度
            sample_embedding = self.generate_embeddings("sample text")[0]
            OpenAIEmbeddings._ndims_cache = len(sample_embedding)
            logger.info(f"模型 {self.model_name} 的嵌入向量维度: {OpenAIEmbeddings._ndims_cache}")
            
        return OpenAIEmbeddings._ndims_cache

    @lru_cache(maxsize=1)
    def _embedding_client(self) -> OpenAI:
        return OpenAI(api_key=self.api_key)
    

class VoyageaiEmbeddings(TextEmbeddingFunction):
    """
    Voyage AI嵌入向量生成器，支持自动批处理
    """
    model_name: str = Field(default="voyage-2", description="Embedding model name")
    api_key: Optional[str] = Field(default=None, description="Embedding API key")
    
    # 类级别的配置参数 - 使用ClassVar标注
    max_tokens: ClassVar[int] = 31000
    max_tokens_per_batch: ClassVar[int] = 120000
    model: ClassVar[str] = "voyage-code-3"
    max_texts_per_batch: ClassVar[int] = 1000
    thread_count: ClassVar[int] = 20
    retry_count: ClassVar[int] = 3
    retry_delay: ClassVar[float] = 1.0
    
    # 缓存维度值作为类变量
    _ndims_cache: ClassVar[Optional[int]] = None
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 仅初始化必要的API配置
        self.api_key = os.getenv("EMBEDDING_API_KEY")
        self.model_name = self.model

        if not self.api_key:
            logger.warning("未找到API密钥，请确保设置了EMBEDDING_API_KEY环境变量")
            
        logger.info(f"VoyageaiEmbeddings初始化完成: 模型={self.model_name}")

    
    def generate_embeddings(self, texts) -> List[List[float]]:
        """使用多线程处理大量文本"""
        if isinstance(texts, str):
            texts = [texts]
            
        # 单个文本直接处理
        if len(texts) <= 1:
            client = self._embedding_client()
            result = client.embed(texts, model=self.model_name, input_type="document")
            return result.embeddings
            
        # 创建批次，并记录每个批次所对应的原始索引
        batches = []
        batch_indices = []  # 记录每个批次中文本的原始索引
        
        tokenizer = VoyageaiEmbeddingTokenizer()
        current_batch = []
        current_indices = []  # 当前批次的索引
        current_token_count = 0
        
        for i, text in enumerate(texts):
            text_token_count = tokenizer.get_token_count(text)
            
            # 如果当前文本会导致批次超过限制，则创建新批次
            if (current_token_count + text_token_count > self.max_tokens_per_batch or 
                len(current_batch) >= self.max_texts_per_batch):
                if current_batch:  # 避免创建空批次
                    batches.append(current_batch)
                    batch_indices.append(current_indices)
                    current_batch = []
                    current_indices = []
                    current_token_count = 0
            
            # 添加文本到当前批次
            current_batch.append(text)
            current_indices.append(i)  # 记录原始索引
            current_token_count += text_token_count
        
        # 添加最后一个批次
        if current_batch:
            batches.append(current_batch)
            batch_indices.append(current_indices)
        
        total_batches = len(batches)
        logger.info(f"总文本数: {len(texts)}，分为 {total_batches} 个批次，使用 {self.thread_count} 个线程处理")
        
        # 预分配结果数组，确保顺序正确
        all_embeddings = [None] * len(texts)
        
        # 用于统计的局部变量
        total_requests = 0
        successful_requests = 0
        failed_requests = 0
        
        def process_batch(batch_idx, batch, indices):
            """内部函数处理单个批次，返回嵌入向量和对应的原始索引"""
            nonlocal total_requests, successful_requests, failed_requests
            
            for attempt in range(self.retry_count):
                try:
                    total_requests += 1
                    client = self._embedding_client()
                    
                    start_time = time.time()
                    result = client.embed(batch, model=self.model_name, input_type="document")
                    elapsed_time = time.time() - start_time
                    
                    successful_requests += 1
                    logger.info(f"批次 {batch_idx+1}/{total_batches} 处理完成，耗时 {elapsed_time:.2f} 秒")
                    
                    # 返回嵌入向量和对应的原始索引
                    return result.embeddings, indices
                except Exception as e:
                    failed_requests += 1
                    if attempt < self.retry_count - 1:
                        logger.warning(f"批次 {batch_idx+1}/{total_batches} 处理失败 (尝试 {attempt+1}/{self.retry_count}): {str(e)}，将在 {self.retry_delay} 秒后重试")
                        time.sleep(self.retry_delay)
                    else:
                        # 如果这是最后一次尝试并且批次有多条文本，尝试单条处理
                        if len(batch) > 1:
                            logger.error(f"批次 {batch_idx+1}/{total_batches} 最终失败，尝试单条处理: {str(e)}")
                            # 逐条处理
                            single_embeddings = {}  # 使用字典存储索引和嵌入
                            for j, (text, orig_idx) in enumerate(zip(batch, indices)):
                                try:
                                    single_client = self._embedding_client()
                                    single_result = single_client.embed([text], model=self.model_name, input_type="document")
                                    single_embeddings[orig_idx] = single_result.embeddings[0]
                                    logger.info(f"批次 {batch_idx+1} 中的文本 {j+1}/{len(batch)} 单独处理成功")
                                except Exception as e2:
                                    logger.error(f"批次 {batch_idx+1} 中的文本 {j+1}/{len(batch)} 单独处理失败: {str(e2)}")
                            
                            if single_embeddings:
                                # 返回成功处理的单条嵌入和它们的索引
                                return list(single_embeddings.values()), list(single_embeddings.keys())
                        
                        logger.error(f"批次 {batch_idx+1}/{total_batches} 最终处理失败: {str(e)}")
                        raise
        
        # 使用ThreadPool处理批次
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_count) as executor:
            # 提交所有批次任务
            future_to_batch_idx = {
                executor.submit(process_batch, i, batch, indices): i 
                for i, (batch, indices) in enumerate(zip(batches, batch_indices))
            }
            
            # 处理结果
            for future in concurrent.futures.as_completed(future_to_batch_idx):
                batch_idx = future_to_batch_idx[future]
                try:
                    batch_embeddings, indices = future.result()
                    
                    # 将结果放入对应的位置，确保顺序正确
                    for embed, orig_idx in zip(batch_embeddings, indices):
                        all_embeddings[orig_idx] = embed
                        
                except Exception as e:
                    logger.error(f"批次 {batch_idx+1}/{total_batches} 处理失败: {str(e)}")
        
        # 检查是否有未完成的嵌入
        if None in all_embeddings:
            missing_indices = [i for i, e in enumerate(all_embeddings) if e is None]
            logger.warning(f"有 {len(missing_indices)} 个文本未能生成嵌入向量")
            
            # 单独处理未完成文本
            for i in missing_indices:
                try:
                    client = self._embedding_client()
                    result = client.embed([texts[i]], model=self.model_name, input_type="document")
                    all_embeddings[i] = result.embeddings[0]
                    logger.info(f"单独处理文本 {i} 成功")
                except Exception as e:
                    logger.error(f"单独处理文本 {i} 失败: {str(e)}")
                    # 如果仍然失败，填充一个零向量避免程序崩溃
                    if self._ndims_cache:
                        all_embeddings[i] = [0.0] * self._ndims_cache
        
        logger.info(f"嵌入处理完成。总请求: {total_requests}, 成功: {successful_requests}, 失败: {failed_requests}")
        
        return all_embeddings
    
    def _create_batches(self, texts) -> List[List[str]]:
        """根据token数和文本数量创建批次"""
        batches = []
        current_batch = []
        current_token_count = 0
        
        tokenizer = VoyageaiEmbeddingTokenizer()
        
        for text in texts:
            # 对Voyage AI，我们需要提前计算token数量
            text_token_count = tokenizer.get_token_count(text)
            
            # 如果当前文本会导致批次超过限制，则创建新批次
            if (current_token_count + text_token_count > self.max_tokens_per_batch or 
                len(current_batch) >= self.max_texts_per_batch):
                if current_batch:  # 避免创建空批次
                    batches.append(current_batch)
                    current_batch = []
                    current_token_count = 0
            
            # 添加文本到当前批次
            current_batch.append(text)
            current_token_count += text_token_count
        
        # 添加最后一个批次
        if current_batch:
            batches.append(current_batch)
        
        return batches


    def ndims(self) -> int:
        """
        返回嵌入向量的维度，使用类缓存
        """
        if VoyageaiEmbeddings._ndims_cache is None:
            # 为单个文本生成嵌入向量并缓存维度
            sample_embedding = self.generate_embeddings("sample text")[0]
            VoyageaiEmbeddings._ndims_cache = len(sample_embedding)
            logger.info(f"模型 {self.model_name} 的嵌入向量维度: {VoyageaiEmbeddings._ndims_cache}")
            
        return VoyageaiEmbeddings._ndims_cache

    @lru_cache(maxsize=1)
    def _embedding_client(self):
        return voyageai.Client(api_key=self.api_key)
    

class OpenAIEmbeddingTokenizer():
    def __init__(self):
        self.encoding = tiktoken.get_encoding('cl100k_base')
        # 直接引用对应Embedding类的max_tokens
        self.max_tokens = OpenAIEmbeddings.max_tokens
        self.model_name = OpenAIEmbeddings.model

    def get_token_count(self, text):
        if not isinstance(text, str):
            return 0
        return len(self.encoding.encode(text))
    
    def detokenize_to_max_tokens(self, text, max_tokens=None):
        if not isinstance(text, str):
            return ""
            
        # 如果没有指定max_tokens，使用默认值
        if max_tokens is None:
            max_tokens = self.max_tokens
        else:
            max_tokens = int(max_tokens)
            
        tokens = self.encoding.encode(text)
        original_token_count = len(tokens)
        
        if original_token_count > max_tokens:
            tokens = tokens[:max_tokens]
            clipped_text = self.encoding.decode(tokens)
            return clipped_text
        
        return text
    
class VoyageaiEmbeddingTokenizer():
    def __init__(self):
        self.api_key = os.getenv("EMBEDDING_API_KEY")
        self._client = None
        # 直接引用对应Embedding类的max_tokens和model
        self.max_tokens = VoyageaiEmbeddings.max_tokens
        self.model_name = VoyageaiEmbeddings.model
        
    @property
    def client(self):
        if self._client is None and self.api_key:
            self._client = voyageai.Client(api_key=self.api_key)
        return self._client

    def get_token_count(self, text):
        if not isinstance(text, str) or not text.strip():
            return 0
            
        try:
            if not self.client:
                # 如果无法初始化客户端，使用简单的估算
                return len(text) // 4
                
            return self.client.count_tokens([text], model=self.model_name)
        except Exception as e:
            logger.warning(f"无法获取token数量: {e}，使用估算值")
            return len(text) // 4
        
    def detokenize_to_max_tokens(self, text, max_tokens=None):
        if not isinstance(text, str):
            return ""
            
        # 如果没有指定max_tokens，使用默认值
        if max_tokens is None:
            max_tokens = self.max_tokens
        else:
            max_tokens = int(max_tokens)
            
        try:
            original_token_count = self.get_token_count(text)
            
            # 如果未超过限制，直接返回
            if original_token_count <= max_tokens:
                return text
                
            # 超过限制，逐步截断
            while original_token_count > max_tokens:
                # 截断10%的文本
                reduction = max(1, int(len(text) * 0.1))
                text = text[:-reduction]
                original_token_count = self.get_token_count(text)
                
            return text
        except Exception as e:
            logger.warning(f"文本截断失败: {e}，进行粗略截断")
            # 如果token计数失败，按照每4个字符1个token的粗略估计截断
            char_limit = max_tokens * 4
            if len(text) > char_limit:
                return text[:char_limit]
            return text
    
def register_custom_embeddings():
    registry = EmbeddingFunctionRegistry.get_instance()

    # 注册自定义嵌入向量生成器
    decorator = registry.register("custom-embeddings")
    
    # 选择要使用的嵌入向量生成器，仅使用EMBEDDING_TYPE环境变量
    embedding_type = os.getenv("EMBEDDING_TYPE").lower()
    print(f"embedding_type: {embedding_type}")
    
    if embedding_type == "openai":
        decorator(OpenAIEmbeddings)
        return OpenAIEmbeddingTokenizer()
    else:
        decorator(VoyageaiEmbeddings)
        return VoyageaiEmbeddingTokenizer()

