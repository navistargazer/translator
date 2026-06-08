import requests
from bs4 import BeautifulSoup

def fetch_novel_text(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        paragraphs = []
        
        # 상단 작가의 말, 본문, 하단 작가의 말 ID를 순서대로 배열해 모두 탐색합니다.
        section_ids = ['novel_p', 'novel_honbun', 'novel_a']
        
        for sec_id in section_ids:
            section = soup.find('div', id=sec_id)
            if section:
                p_tags = section.find_all('p')
                if p_tags:
                    for p in p_tags:
                        text = p.get_text(strip=True)
                        if text:
                            paragraphs.append(text)
                else:
                    # <p> 태그가 없을 경우를 대비한 방어 로직
                    lines = section.get_text(separator='\n').split('\n')
                    for line in lines:
                        text = line.strip()
                        if text:
                            paragraphs.append(text)
        
        if not paragraphs:
            return "오류: 본문 영역을 찾을 수 없습니다. 사이트 구조가 변경되었을 수 있습니다."
            
        return paragraphs
        
    except requests.exceptions.RequestException as e:
        return f"연결 오류가 발생했습니다: {e}"

if __name__ == "__main__":
    # 7화 URL로 직접 테스트해 볼 수 있습니다.
    target_url = "https://ncode.syosetu.com/n1314hd/7/"
    result = fetch_novel_text(target_url)
    
    if isinstance(result, list):
        print(f"총 {len(result)}줄의 문장을 찾았습니다. 정상적으로 파싱되었습니다!")
    else:
        print(result)