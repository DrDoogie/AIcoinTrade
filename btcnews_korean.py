#BTC뉴스 한글로 가져오기

import os
from dotenv import load_dotenv
import pyupbit
import pandas as pd
import json
from openai import OpenAI
import ta
from ta.utils import dropna
import time
import requests

load_dotenv()

def translate_text(text):
    """OpenAI API를 사용하여 텍스트를 한글로 번역"""
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional translator. Translate the given text into Korean. Maintain the original meaning while making it natural in Korean."
                },
                {
                    "role": "user",
                    "content": f"Translate this text to Korean: {text}"
                }
            ],
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Translation error: {e}")
        return text  # 번역 실패시 원본 반환

def get_bitcoin_news():
    serpapi_key = os.getenv("SERPAPI_API_KEY")
    if not serpapi_key:
        print("SERPAPI API key is missing.")
        return []
        
    url = "https://serpapi.com/search.json"
    params = {
        "engine": "google_news",
        "q": "bitcoin OR btc cryptocurrency",  # 검색어 개선
        "api_key": serpapi_key
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        news_results = data.get("news_results", [])
        headlines = []
        
        # 최신 5개 뉴스만 처리
        for item in news_results[:5]:
            title = item.get("title", "")
            date = item.get("date", "")
            snippet = item.get("snippet", "")
            
            # 제목과 내용 번역
            translated_title = translate_text(title)
            translated_snippet = translate_text(snippet)
            
            headlines.append({
                "original_title": title,
                "translated_title": translated_title,
                "date": date,
                "original_snippet": snippet,
                "translated_snippet": translated_snippet
            })

        return headlines
        
    except requests.RequestException as e:
        print(f"Error fetching news: {e}")
        return []

def print_news():
    """뉴스를 보기 좋게 출력"""
    news = get_bitcoin_news()
    if not news:
        print("뉴스를 가져오는데 실패했습니다.")
        return

    print("\n=== 비트코인 최신 뉴스 ===\n")
    for idx, item in enumerate(news, 1):
        print(f"[뉴스 {idx}]")
        print(f"날짜: {item['date']}")
        print(f"원문 제목: {item['original_title']}")
        print(f"번역 제목: {item['translated_title']}")
        print(f"원문 내용: {item['original_snippet']}")
        print(f"번역 내용: {item['translated_snippet']}")
        print("-" * 80 + "\n")

if __name__ == "__main__":
    print_news()