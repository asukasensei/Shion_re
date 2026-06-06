# Please install OpenAI SDK first: `pip3 install openai`
import os
from openai import OpenAI

client = OpenAI(
    api_key="",
    base_url="https://api.deepseek.com")


while True:
    content = input("请输入：")
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": "You are a cute anime girl.回答要像一个可爱的动漫女孩一样。"},
            {"role": "user", "content": "{content}"},
        ],
        stream=True,
        extra_body={"thinking": {"type": "disabled"}}
    )
    content = ""

    for chunk in response:
            print(chunk.choices[0].delta.content)
            content += chunk.choices[0].delta.content

