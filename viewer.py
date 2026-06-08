import os
import re
import json
import threading
import queue
import time
import unicodedata  # macOS NFD 자소 분리 정규화 복원용
import zipfile
import io
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk



def natural_sort_key(s):
    """
    문자열 내부의 숫자(소수 포함)를 임시로 '정수부 9자리 + 소수부 3자리'의 고정폭 문자열로 치환하여 정렬 키를 생성합니다.
    타입이 100% str 단일 형식을 유지하므로 TypeError를 원천 방지하며, macOS Finder와 완벽히 호환되는 자연 정렬(1 -> 2 -> 10)을 지원합니다.
    """
    def pad(match):
        val = float(match.group(1))
        # 예: 8.5 -> "000000008.500", 10 -> "000000010.000"
        return f"{int(val):09d}.{int(round((val - int(val)) * 1000)):03d}"
    return re.sub(r'(\d+(?:\.\d+)?)', pad, s)


class ImagePreloader:
    """고해상도 만화 이미지 파일을 백그라운드 스레드에서 비동기식으로 open 및 캐싱하는 클래스 (인메모리 ZIP 지원)"""
    def __init__(self, file_paths, cache_size=5, zip_path=None):
        self.file_paths = file_paths
        self.zip_path = zip_path
        self.cache = {}  # {index: PIL.Image}
        self.cache_lock = threading.Lock()
        self.cache_size = cache_size
        
        self.preload_queue = queue.Queue()
        self.running = True
        self.worker_thread = threading.Thread(target=self._preload_worker, daemon=True)
        self.worker_thread.start()

    def update_paths(self, file_paths, zip_path=None):
        """새로운 에피소드로 이동할 때 파일 목록을 갱신하고 캐시를 초기화합니다."""
        with self.cache_lock:
            self.file_paths = file_paths
            self.zip_path = zip_path
            self.cache.clear()
        
        # 이전 대기 큐 비우기
        while not self.preload_queue.empty():
            try:
                self.preload_queue.get_nowait()
            except queue.Empty:
                break

    def request_preload(self, current_index):
        """현재 인덱스를 기준으로 앞뒤 이미지들을 우선 순위로 큐에 추가합니다."""
        if not self.file_paths:
            return

        total = len(self.file_paths)
        indices_to_preload = []

        # 현재 뷰, 다음 3장, 이전 1장 순서로 우선 로딩
        for offset in [0, 1, 2, 3, -1]:
            idx = current_index + offset
            if 0 <= idx < total:
                indices_to_preload.append(idx)

        # 큐에 로딩 타겟 추가
        for idx in indices_to_preload:
            with self.cache_lock:
                if idx not in self.cache:
                    self.preload_queue.put(idx)

        # 캐시 크기 관리 (범위 밖 캐시 데이터 정리)
        with self.cache_lock:
            for cached_idx in list(self.cache.keys()):
                if cached_idx < current_index - 3 or cached_idx > current_index + 5:
                    del self.cache[cached_idx]

    def get_image(self, index):
        """특정 인덱스의 이미지를 가져옵니다. 캐시에 없으면 동기식으로 로드합니다."""
        if not self.file_paths or index < 0 or index >= len(self.file_paths):
            return None

        # 1. 캐시에서 조회
        with self.cache_lock:
            if index in self.cache:
                return self.cache[index]

        # 2. 캐시에 없는 경우 동기적으로 즉시 로드
        try:
            if self.zip_path:
                with zipfile.ZipFile(self.zip_path, 'r') as zf:
                    data = zf.read(self.file_paths[index])
                    img = Image.open(io.BytesIO(data))
            else:
                img = Image.open(self.file_paths[index])
                
            # RGB 형태로 강제 변환하여 다양한 이미지 형식(GIF, PNG 등) 호환성 확보
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            
            with self.cache_lock:
                self.cache[index] = img
            return img
        except Exception as e:
            print(f"이미지 로딩 실패 ({self.file_paths[index]}): {e}")
            return None

    def _preload_worker(self):
        """백그라운드 스레드에서 큐를 꺼내 이미지를 디스크 또는 ZIP에서 로딩합니다."""
        while self.running:
            try:
                # 타임아웃을 두어 정기적으로 루프 탈출 가능하게 설계
                index = self.preload_queue.get(timeout=0.5)
                
                with self.cache_lock:
                    if index in self.cache or index >= len(self.file_paths) or index < 0:
                        self.preload_queue.task_done()
                        continue
                    current_zip_path = self.zip_path

                try:
                    if current_zip_path:
                        with zipfile.ZipFile(current_zip_path, 'r') as zf:
                            data = zf.read(self.file_paths[index])
                            img = Image.open(io.BytesIO(data))
                    else:
                        img = Image.open(self.file_paths[index])
                        
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGB")
                    
                    with self.cache_lock:
                        # 큐 처리 도중 캐시 최대치 보존
                        if len(self.cache) < self.cache_size * 2:
                            self.cache[index] = img
                except Exception:
                    pass

                self.preload_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass

    def stop(self):
        self.running = False



class ComicViewerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📖 다크 코믹 뷰어 (Comic Viewer)")
        self.root.geometry("1100x750")
        self.root.minsize(800, 600)

        # 상태 설정 변수
        self.comic_root_dir = "/Volumes/MacSSD/Comics"
        self.current_comic = ""
        self.current_episode = ""
        self.episodes_list = []  # 현재 선택된 만화의 전체 에피소드 리스트
        self.image_files = []
        self.current_page = 0
        
        # 감상 설정: RTL(Right-to-Left)가 기본값
        self.read_direction = "RTL"  # "RTL" 또는 "LTR"
        self.view_mode = "2PAGE"     # "2PAGE" (기본 양면 병합) 또는 "1PAGE" (단면 1장 / 펼침면 가로 분할)
        self.sidebar_visible = True
        self.fullscreen_active = False
        self.was_sidebar_visible = True  # 전체화면 토글 전 레이아웃 복원용 상태 변수
        self.control_bar_visible = False  # 킨들 스타일 중앙 클릭 메뉴 토글 상태 플래그
        
        # 피벗/세로 모드 전용 가상 서브페이지 조각 인덱스 (0: 첫 파트, 1: 둘째 파트)
        self.current_sub_page = 0
        
        # 마우스 휠 오작동 방지 (디바운싱 타임스탬프)
        self.last_wheel_time = 0

        # UI 색상 시스템 (macOS 라이트 & 실버 글래스 테마)
        self.bg_color = "#f5f5f7"       # 애플 표준 라이트 실버
        self.sidebar_bg = "#ffffff"     # 깨끗한 화이트
        self.accent_color = "#007aff"   # 애플 시스템 블루 (호버 강조)
        self.text_color = "#1d1d1f"     # 애플 다크 차콜
        self.sub_text = "#86868b"       # 애플 미디엄 그레이
        self.border_color = "#e5e5ea"   # 연한 실버 보더

        self.root.configure(bg=self.bg_color)
        
        # 이미지 프리로더 (초기화)
        self.preloader = ImagePreloader([])

        # 히스토리 로드
        self.history_file = os.path.expanduser("~/.gemini/antigravity-ide/comic_viewer_history.json")
        self.load_history()

        # UI 레이아웃 구축
        self.setup_ui()
        
        # 단축키 및 이벤트 바인딩
        self.bind_events()

        # 히스토리 기반 초기 폴더 리스팅
        self.refresh_library()
        self.restore_last_read()

    def setup_ui(self):
        # 전체 화면 구조: 좌측 사이드바 & 우측 캔버스
        self.main_pane = tk.PanedWindow(self.root, orient="horizontal", bg=self.border_color, bd=0, sashwidth=4)
        self.main_pane.pack(fill="both", expand=True)

        # 1. 좌측 탐색기 프레임 (사이드바)
        self.sidebar = tk.Frame(self.main_pane, bg=self.sidebar_bg, width=260)
        self.sidebar.pack_propagate(False)
        self.main_pane.add(self.sidebar, minsize=200)

        # 사이드바 상단 조작 버튼
        sidebar_top = tk.Frame(self.sidebar, bg=self.sidebar_bg, pady=10, padx=10)
        sidebar_top.pack(fill="x")

        lib_label = tk.Label(
            sidebar_top,
            text="📚 만화 라이브러리",
            font=("Apple SD Gothic Neo", 13, "bold"),
            fg=self.text_color,
            bg=self.sidebar_bg
        )
        lib_label.pack(side="left")

        # 폴더 선택 아이콘형 라벨 버튼
        folder_btn = tk.Label(
            sidebar_top,
            text="📂",
            font=("Apple SD Gothic Neo", 12),
            fg=self.accent_color,
            bg=self.sidebar_bg,
            cursor="hand2"
        )
        folder_btn.pack(side="right")
        folder_btn.bind("<Button-1>", lambda e: self.select_root_directory())

        # 사이드바 계층 탐색 트리
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Custom.Treeview",
            background=self.sidebar_bg,
            foreground=self.text_color,
            fieldbackground=self.sidebar_bg,
            rowheight=26,
            borderwidth=0,
            font=("Apple SD Gothic Neo", 11)
        )
        style.map("Custom.Treeview", background=[("selected", self.accent_color)], foreground=[("selected", "#ffffff")])
        style.configure("Custom.Treeview.Heading", background=self.sidebar_bg, foreground=self.text_color, borderwidth=0)

        # 스크롤바와 트리 패키징
        tree_frame = tk.Frame(self.sidebar, bg=self.sidebar_bg)
        tree_frame.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        self.tree = ttk.Treeview(
            tree_frame,
            style="Custom.Treeview",
            show="tree",
            selectmode="browse"
        )
        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        # 트리 클릭 이벤트
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        # 2. 우측 메인 뷰어 프레임
        self.viewer_frame = tk.Frame(self.main_pane, bg=self.bg_color)
        self.main_pane.add(self.viewer_frame, minsize=400)

        # 캔버스 렌더러
        self.canvas = tk.Canvas(
            self.viewer_frame,
            bg=self.bg_color,
            bd=0,
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        # 최초에 툴바 숨기기
        self.control_bar_visible = False

    def show_control_bar(self):
        """컨트롤바 상태를 노출로 설정하고 화면을 즉시 갱신 리드로우합니다."""
        self.control_bar_visible = True
        self.show_page(self.current_page)

    def hide_control_bar(self):
        """컨트롤바 상태를 숨김으로 설정하고 화면을 즉시 갱신 리드로우합니다."""
        self.control_bar_visible = False
        self.show_page(self.current_page)

    def select_root_directory(self):
        """사용자가 라이브러리로 탐색할 만화 루트 디렉토리를 변경합니다."""
        selected = filedialog.askdirectory(initialdir=self.comic_root_dir)
        if selected:
            self.comic_root_dir = selected
            self.refresh_library()
            self.save_history()

    def refresh_library(self):
        """Comics 디렉토리 내의 구조를 스캔하여 좌측 트리 목록에 로드합니다."""
        # 트리 내용 삭제
        for i in self.tree.get_children():
            self.tree.delete(i)

        if not os.path.exists(self.comic_root_dir):
            return

        try:
            # 1단계: 만화 제목 목록 (최상위 노드) - 맥OS NFD 자소분리 충돌 방지를 위해 NFC(완성형)로 정규화
            comics = [
                unicodedata.normalize('NFC', d) for d in os.listdir(self.comic_root_dir)
                if os.path.isdir(os.path.join(self.comic_root_dir, d))
            ]
            comics.sort(key=natural_sort_key)  # 타입 안전 자연 정렬 적용

            for comic in comics:
                comic_path = os.path.join(self.comic_root_dir, comic)
                comic_node = self.tree.insert("", "end", text=f"📁 {comic}", values=(comic_path, "comic"))

                # 2단계: 개별 만화 아래의 에피소드 회차 목록 (폴더 및 zip/cbz 파일) - NFC 정규화 적용
                valid_archive_exts = (".zip", ".cbz")
                episodes = [
                    unicodedata.normalize('NFC', d) for d in os.listdir(comic_path)
                    if os.path.isdir(os.path.join(comic_path, d)) or d.lower().endswith(valid_archive_exts)
                ]
                episodes.sort(key=natural_sort_key)  # 타입 안전 자연 정렬 적용

                for ep in episodes:
                    ep_path = os.path.join(comic_path, ep)
                    self.tree.insert(comic_node, "end", text=f"📄 {ep}", values=(ep_path, "episode"))
        except Exception as e:
            print(f"라이브러리 갱신 에러: {e}")

    def on_tree_select(self, event):
        """트리뷰에서 특정 노드가 선택되었을 때의 핸들러"""
        selected_items = self.tree.selection()
        if not selected_items:
            return

        item = selected_items[0]
        path, node_type = self.tree.item(item, "values")
        text = self.tree.item(item, "text").replace("📁 ", "").replace("📄 ", "")

        if node_type == "episode":
            # 만화 제목과 에피소드명 셋업
            parent_item = self.tree.parent(item)
            self.current_comic = self.tree.item(parent_item, "text").replace("📁 ", "")
            self.current_episode = text
            
            # 현재 만화의 모든 에피소드 리스트 추출 (연속 넘기기 용도)
            self.episodes_list = []
            for child in self.tree.get_children(parent_item):
                c_path, _ = self.tree.item(child, "values")
                c_text = self.tree.item(child, "text").replace("📄 ", "")
                self.episodes_list.append((c_text, c_path))

            # 이미지 로드 시작
            self.load_episode_images(path)
            self.current_page = 0
            self.show_page(self.current_page)
            self.save_history()

    def load_episode_images(self, path):
        """선택된 회차 폴더 또는 압축파일 내의 이미지 파일들을 탐색하여 정렬 로드합니다."""
        valid_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp")
        valid_archive_exts = (".zip", ".cbz")
        
        # 상태 변수 초기화
        self.is_zip_episode = False
        self.zip_path = None
        
        try:
            if os.path.isfile(path) and path.lower().endswith(valid_archive_exts):
                self.is_zip_episode = True
                self.zip_path = path
                with zipfile.ZipFile(path, 'r') as zf:
                    # zip 파일 내부의 이미지 목록 스캔 (macOS용 __MACOSX 메타 폴더 제외)
                    files = [
                        name for name in zf.namelist()
                        if not name.startswith('__MACOSX') and name.lower().endswith(valid_extensions)
                    ]
                    files.sort(key=natural_sort_key)
                    self.image_files = files
                    # 프리로더 업데이트 (zip_path 인자 전달)
                    self.preloader.update_paths(self.image_files, zip_path=self.zip_path)
            else:
                files = [
                    os.path.join(path, f) for f in os.listdir(path)
                    if os.path.isfile(os.path.join(path, f)) and f.lower().endswith(valid_extensions)
                ]
                files.sort(key=natural_sort_key)
                self.image_files = files
                # 프리로더 업데이트 (일반 폴더)
                self.preloader.update_paths(self.image_files, zip_path=None)
        except Exception as e:
            print(f"이미지 탐색 실패: {e}")
            self.image_files = []

    def crop_half_page(self, pil_img, sub_page):
        """
        가로가 긴 2페이지 펼침면 이미지를 세로 모드 창의 종횡비에 맞게 정밀하게 절반으로 잘라냅니다.
        RTL 모드 시 첫 번째 조각(sub_page=0)이 우측 절반, 둘째 조각(sub_page=1)이 좌측 절반이 되도록 분할합니다.
        """
        w, h = pil_img.size
        w_half = w // 2

        if self.read_direction == "RTL":
            if sub_page == 0:
                return pil_img.crop((w_half, 0, w, h))  # 첫 번째 파트: 우측 절반
            else:
                return pil_img.crop((0, 0, w_half, h))  # 두 번째 파트: 좌측 절반
        else:
            if sub_page == 0:
                return pil_img.crop((0, 0, w_half, h))  # 첫 번째 파트: 좌측 절반
            else:
                return pil_img.crop((w_half, 0, w, h))  # 두 번째 파트: 우측 절반

    def get_current_view_specs(self, index):
        """
        현재 인덱스를 기준으로 화면에 띄울 이미지 인덱스 목록과 병합 여부를 분석합니다.
        1페이지 보기 모드(self.view_mode == "1PAGE")인 경우 병합을 미적용하고 단일 렌더링으로 고정합니다.
        """
        if not self.image_files or index < 0 or index >= len(self.image_files):
            return ([], False)

        if self.view_mode == "1PAGE":
            return ([index], False)

        # [더 좋은 대안 - 표지 단독 렌더링]: 첫 번째 페이지(표지, Index 0)는 무조건 양면 병합에서
        # 제외하고 단독으로 띄워 감상하게 함으로써, 이후 에피소드 전체의 좌우 펼침 짝이 어긋나는 현상을 기본 예방합니다.
        if index == 0:
            return ([0], False)

        # 1. 첫 번째 이미지 정보 확인
        img1 = self.preloader.get_image(index)
        if not img1:
            return ([index], False)

        w1, h1 = img1.size
        # 가로 비율이 세로보다 확실하게 긴 이미지(1.1배 초과)는 이미 2페이지 펼침면이므로 단일 렌더링
        if w1 > h1 * 1.1:
            return ([index], False)

        # 2. 다음 이미지가 단면인지 판단하여 RTL 2페이지 병합 결정
        next_idx = index + 1
        if next_idx < len(self.image_files):
            img2 = self.preloader.get_image(next_idx)
            if img2:
                w2, h2 = img2.size
                # 다음 이미지 역시 단면(세로가 긴 형태)이면 2페이지 결합
                if w2 <= h2 * 1.1:
                    return ([index, next_idx], True)

        # 다음 장이 없거나 펼침면이어서 결합할 수 없으면 단일 렌더링
        return ([index], False)

    def get_prev_page_index(self, index):
        """이전 페이지로 뒤돌아갈 때 시작할 인덱스를 지능적으로 역산합니다 (가로 양면 전용)."""
        if index <= 0:
            return -1

        prev_idx = index - 1
        if prev_idx <= 0:
            return 0

        # index - 2와 index - 1 두 장이 모두 단면(가로 병합 대상)인지 역추적
        prev_prev_idx = prev_idx - 1
        img1 = self.preloader.get_image(prev_prev_idx)
        img2 = self.preloader.get_image(prev_idx)

        if img1 and img2:
            w1, h1 = img1.size
            w2, h2 = img2.size
            if w1 <= h1 * 1.1 and w2 <= h2 * 1.1:
                return prev_prev_idx

        return prev_idx

    def combine_two_pages(self, img_first, img_second):
        """
        두 세로 단면 이미지를 감상 방향(RTL/LTR)에 따라 가로 양면 페이지로 매끄럽게 Concat합니다.
        세로 해상도를 큰 쪽으로 맞추어 비율 유지 결합을 수행합니다. (속도 향상을 위해 BILINEAR 적용)
        """
        h_target = max(img_first.size[1], img_second.size[1])

        w1, h1 = img_first.size
        w1_target = int(w1 * (h_target / h1))
        img1_scaled = img_first.resize((w1_target, h_target), Image.Resampling.BILINEAR)

        w2, h2 = img_second.size
        w2_target = int(w2 * (h_target / h2))
        img2_scaled = img_second.resize((w2_target, h_target), Image.Resampling.BILINEAR)

        combined_width = w1_target + w2_target
        combined_img = Image.new("RGB", (combined_width, h_target), self.bg_color)

        if self.read_direction == "RTL":
            combined_img.paste(img2_scaled, (0, 0))           # 좌측에 2번째 페이지 (index + 1)
            combined_img.paste(img1_scaled, (w2_target, 0))    # 우측에 1번째 페이지 (index)
        else:
            combined_img.paste(img1_scaled, (0, 0))           # 좌측에 1번째 페이지 (index)
            combined_img.paste(img2_scaled, (w1_target, 0))    # 우측에 2번째 페이지 (index + 1)

        return combined_img

    def show_page(self, page_index):
        """지정된 인덱스를 바탕으로 수동 설정 모드(2페이지 양면 Concat / 1페이지 단독 & 펼침면 자르기) 화면을 렌더링합니다."""
        if not self.image_files:
            self.canvas.delete("all")
            self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text="감상할 에피소드를 왼쪽 트리에서 더블클릭하여 선택해 주세요.",
                fill=self.sub_text,
                font=("Apple SD Gothic Neo", 12),
                justify="center"
            )
            self.page_label.config(text="0 / 0 Page")
            return

        if page_index < 0 or page_index >= len(self.image_files):
            return

        self.current_page = page_index

        canvas_width = max(self.canvas.winfo_width(), 100)
        canvas_height = max(self.canvas.winfo_height(), 100)
        is_one_page_mode = (self.view_mode == "1PAGE")

        pil_img = None
        is_combined = False
        is_split = False

        if is_one_page_mode:
            # [1페이지 감상 모드]: 병합을 끄고, 펼침면(가로가 긴 2페이지 단일 이미지)인 경우만 가로 절반 분할
            raw_img = self.preloader.get_image(page_index)
            if raw_img:
                w, h = raw_img.size
                if w > h * 1.1:
                    # 펼침면은 가로 절반을 쪼개어 가상 서브페이지 단위로 렌더링
                    pil_img = self.crop_half_page(raw_img, self.current_sub_page)
                    is_split = True
                else:
                    pil_img = raw_img
                    self.current_sub_page = 0
        else:
            # [2페이지 감상 모드]: 스마트 양면 결합 렌더링 진행
            indices, is_combined = self.get_current_view_specs(page_index)

            for idx in indices:
                self.preloader.request_preload(idx)

            if is_combined and len(indices) == 2:
                img_first = self.preloader.get_image(indices[0])
                img_second = self.preloader.get_image(indices[1])
                if img_first and img_second:
                    pil_img = self.combine_two_pages(img_first, img_second)
            else:
                pil_img = self.preloader.get_image(page_index)

        if not pil_img:
            self.canvas.delete("all")
            self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text="이미지 디코딩 에러 발생",
                fill="#ff5a5f",
                font=("Apple SD Gothic Neo", 12)
            )
            return

        # 3. 캔버스 리사이징 및 렌더 (작은 이미지는 캔버스에 맞춰 자동 확대 지원 및 고속 BILINEAR 필터 적용)
        img_width, img_height = pil_img.size
        ratio_w = canvas_width / img_width
        ratio_h = canvas_height / img_height
        scale = min(ratio_w, ratio_h)

        new_width = int(img_width * scale)
        new_height = int(img_height * scale)

        if new_width > 0 and new_height > 0:
            resized_pil = pil_img.resize((new_width, new_height), Image.Resampling.BILINEAR)
            self.tk_image = ImageTk.PhotoImage(resized_pil)

            self.canvas.delete("all")
            self.canvas.create_image(
                canvas_width / 2,
                canvas_height / 2,
                image=self.tk_image,
                anchor="center"
            )

        # 4. 가상 제어 바 (하단 플로팅 컨트롤 메뉴) 반투명 렌더링
        if self.control_bar_visible:
            # 2배로 확장 설계된 좌표 및 크기 계산
            bg_w = canvas_width * 0.85
            bg_h = 90
            bx = canvas_width / 2
            by = canvas_height * 0.88  # 화면 하단에 알맞게 정렬
            
            # Pillow RGBA를 활용해 둥근 모서리 화이트 글래스(Alpha=210) 패널 생성
            control_bg_img = Image.new("RGBA", (int(bg_w), int(bg_h)), (0, 0, 0, 0))
            from PIL import ImageDraw
            draw = ImageDraw.Draw(control_bg_img)
            # 둥근 모서리 반경 20px 및 세련된 연한 실버 테두리
            draw.rounded_rectangle(
                [0, 0, bg_w - 1, bg_h - 1], radius=20,
                fill=(255, 255, 255, 210),  # 반투명 화이트 글래스
                outline=(220, 220, 225, 240), # 매우 밝은 세미실버 테두리
                width=2
            )
            
            self.control_tk_bg = ImageTk.PhotoImage(control_bg_img)
            
            # 캔버스에 반투명 제어바 플레이트 추가
            self._control_bg_id = self.canvas.create_image(
                bx, by,
                image=self.control_tk_bg,
                anchor="center"
            )
            
            # 폰트 및 텍스트 2배 크게 조정 (18pt)
            font_size = 18
            x1 = bx - bg_w / 2
            x2 = bx + bg_w / 2
            
            # A. 정렬 버튼
            align_text = f"정렬: {self.read_direction} ({'우→좌' if self.read_direction == 'RTL' else '좌→우'})"
            self._btn_align_id = self.canvas.create_text(
                x1 + 60, by,
                text=align_text,
                fill=self.text_color,
                font=("Apple SD Gothic Neo", font_size, "bold"),
                anchor="w",
                tags="btn_align"
            )
            
            # B. 보기 모드 버튼
            mode_text = f"보기: {'1페이지' if self.view_mode == '1PAGE' else '2페이지'}"
            self._btn_mode_id = self.canvas.create_text(
                x1 + 330, by,
                text=mode_text,
                fill=self.text_color,
                font=("Apple SD Gothic Neo", font_size, "bold"),
                anchor="w",
                tags="btn_mode"
            )
            
            # C. 페이지 진행 레이블 (중앙 배치)
            if is_one_page_mode:
                if is_split:
                    progress_text = f"{self.current_page + 1}화 ({self.current_sub_page + 1}/2 조각) / {len(self.image_files)} Page"
                else:
                    progress_text = f"{self.current_page + 1} / {len(self.image_files)} Page"
            else:
                indices, is_combined = self.get_current_view_specs(page_index)
                if is_combined and len(indices) == 2:
                    progress_text = f"{indices[0] + 1}-{indices[1] + 1} / {len(self.image_files)} Page"
                else:
                    progress_text = f"{self.current_page + 1} / {len(self.image_files)} Page"
                    
            self._lbl_page_id = self.canvas.create_text(
                bx, by,
                text=progress_text,
                fill=self.accent_color,
                font=("Apple SD Gothic Neo", font_size + 1, "bold"),
                anchor="center"
            )
            
            # D. 전체 닫기 버튼
            self._btn_close_id = self.canvas.create_text(
                x2 - 60, by,
                text="전체 닫기 (Tab)",
                fill=self.text_color,
                font=("Apple SD Gothic Neo", font_size, "bold"),
                anchor="e",
                tags="btn_close"
            )

    def prev_page(self):
        """이전 페이지로 이동합니다 (2페이지 모드 양면 보폭 / 1페이지 모드 펼침면 쪼개기 지능형 처리)."""
        if not self.image_files:
            return

        is_one_page_mode = (self.view_mode == "1PAGE")

        if is_one_page_mode:
            # [1페이지 모드]: 가상 서브페이지 보폭 튜닝
            if self.current_sub_page == 1:
                # 2번째 파트 조각이었다면 ➡️ 1번째 파트 조각으로 이동
                self.current_sub_page = 0
                self.show_page(self.current_page)
                return

            # 1번째 파트 혹은 일반 단면이었다면 ➡️ 이전 이미지 인덱스로 이동
            prev_idx = self.current_page - 1
            if prev_idx >= 0:
                prev_img = self.preloader.get_image(prev_idx)
                if prev_img:
                    w, h = prev_img.size
                    if w > h * 1.1:
                        # 이전 이미지가 펼침면이면 ➡️ 맨 뒤 조각(2번째 파트)부터 출력
                        self.current_sub_page = 1
                    else:
                        self.current_sub_page = 0
                self.show_page(prev_idx)
            else:
                self.switch_episode(direction=-1)
        else:
            # [2페이지 모드]: 기존 양면 결합용 역방향 인덱싱 적용
            prev_idx = self.get_prev_page_index(self.current_page)
            if prev_idx >= 0:
                self.current_sub_page = 0
                self.show_page(prev_idx)
            else:
                self.switch_episode(direction=-1)

    def next_page(self):
        """다음 페이지로 이동합니다 (2페이지 모드 양면 보폭 / 1페이지 모드 펼침면 쪼개기 지능형 처리)."""
        if not self.image_files:
            return

        is_one_page_mode = (self.view_mode == "1PAGE")

        if is_one_page_mode:
            # [1페이지 모드]: 가상 서브페이지 보폭 튜닝
            img = self.preloader.get_image(self.current_page)
            if img:
                w, h = img.size
                if w > h * 1.1 and self.current_sub_page == 0:
                    # 펼침면의 첫 번째 파트 조각 감상 중이었다면 ➡️ 두 번째 파트 조각으로 이동
                    self.current_sub_page = 1
                    self.show_page(self.current_page)
                    return

            # 단면이거나 펼침면의 두 번째 파트 감상 완료 상태였다면 ➡️ 다음 이미지 인덱스로 이동
            next_idx = self.current_page + 1
            if next_idx < len(self.image_files):
                self.current_sub_page = 0
                self.show_page(next_idx)
            else:
                self.switch_episode(direction=1)
        else:
            # [2페이지 모드]: 기존 양면 결합용 정방향 인덱싱 적용
            indices, _ = self.get_current_view_specs(self.current_page)
            step = len(indices) if indices else 1
            
            next_idx = self.current_page + step
            if next_idx < len(self.image_files):
                self.current_sub_page = 0
                self.show_page(next_idx)
            else:
                self.switch_episode(direction=1)

    def show_toast(self, message):
        """캔버스 하단에 반투명한 안내 메시지(토스트)를 2배 큼직하게 띄우고 1.5초 뒤 자동으로 제거합니다."""
        if hasattr(self, "_toast_id") and self._toast_id:
            self.canvas.delete(self._toast_id)
            self._toast_id = None
        if hasattr(self, "_toast_bg_id") and self._toast_bg_id:
            self.canvas.delete(self._toast_bg_id)
            self._toast_bg_id = None

        canvas_width = max(self.canvas.winfo_width(), 200)
        canvas_height = max(self.canvas.winfo_height(), 200)

        cx = canvas_width / 2
        cy = canvas_height * 0.72  # 자막 등을 고려해 약간 올린 지점 설정

        # 폰트 크기 2배 확대 (11pt -> 22pt)
        font_size = 22
        padding_x = 45
        padding_y = 20
        
        # 글자별 근사 픽셀 너비를 동적 연산하여 배경 스케일 조율
        char_width = 15
        bg_w = len(message) * char_width + padding_x * 2
        bg_h = font_size + padding_y * 2
        
        if bg_w < 200:
            bg_w = 200
            
        # Pillow를 활용하여 극도로 우아한 둥근 모서리 화이트 글래스(Alpha=210) 플레이트 이미지 생성
        toast_bg_img = Image.new("RGBA", (int(bg_w), int(bg_h)), (0, 0, 0, 0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(toast_bg_img)
        # 둥근 모서리 반경 16px 및 얇은 실버/화이트 반투명 테두리 그리기
        draw.rounded_rectangle(
            [0, 0, bg_w - 1, bg_h - 1], radius=16,
            fill=(255, 255, 255, 210),  # 반투명 화이트 글래스
            outline=(220, 220, 225, 240), # 매우 밝은 세미실버 테두리
            width=2
        )
        
        self.toast_tk_bg = ImageTk.PhotoImage(toast_bg_img)
        
        # 캔버스에 반투명 오버레이 투척
        self._toast_bg_id = self.canvas.create_image(
            cx, cy,
            image=self.toast_tk_bg,
            anchor="center"
        )
        
        self._toast_id = self.canvas.create_text(
            cx, cy,
            text=message,
            fill=self.text_color,
            font=("Apple SD Gothic Neo", font_size, "bold")
        )

        def clear_toast():
            if hasattr(self, "_toast_id") and self._toast_id:
                self.canvas.delete(self._toast_id)
                self._toast_id = None
            if hasattr(self, "_toast_bg_id") and self._toast_bg_id:
                self.canvas.delete(self._toast_bg_id)
                self._toast_bg_id = None

        self.root.after(1500, clear_toast)

    def switch_episode(self, direction):
        """에피소드를 이전(-1) 또는 다음(1) 회차로 전환합니다."""
        if not self.current_episode or not self.episodes_list:
            return

        # 현재 인덱스 찾기
        current_idx = -1
        for i, (text, _) in enumerate(self.episodes_list):
            if text == self.current_episode:
                current_idx = i
                break

        if current_idx == -1:
            return

        target_idx = current_idx + direction
        if 0 <= target_idx < len(self.episodes_list):
            target_text, target_path = self.episodes_list[target_idx]
            self.current_episode = target_text
            
            self.sync_tree_selection(target_path)
            self.load_episode_images(target_path)
            
            # 이전 회차로 이동한 경우, 마지막 이미지의 스펙을 파싱해 정확한 페이지 시작점을 설정
            if direction == -1:
                last_idx = len(self.image_files) - 1
                is_one_page_mode = (self.view_mode == "1PAGE")
                
                if is_one_page_mode:
                    # 1페이지 모드: 마지막 이미지 인덱스 설정 및 펼침면인 경우 우측(RTL) 또는 좌측(LTR) 2번째 조각부터 시작
                    self.current_page = last_idx
                    last_img = self.preloader.get_image(last_idx)
                    if last_img:
                        w, h = last_img.size
                        if w > h * 1.1:
                            self.current_sub_page = 1
                        else:
                            self.current_sub_page = 0
                else:
                    # 2페이지 모드: 기존 가로 병합 시작점 산출
                    self.current_page = self.get_prev_page_index(last_idx + 1)
                    self.current_sub_page = 0
            else:
                self.current_page = 0
                self.current_sub_page = 0
                
            self.show_page(self.current_page)
            self.save_history()
            
            # [수정] 캔버스 리사이징 Configure 비동기 딜레이(80ms)에 의해 토스트가 delete("all")로 
            # 즉시 증발되는 타이밍 충돌을 예방하기 위해, 180ms 안전 지연 오버레이 스케줄링 적용
            self.root.after(180, lambda: self.show_toast(f"에피소드 전환: {target_text}"))
        else:
            if direction == 1:
                self.show_toast("현재 만화의 가장 마지막 에피소드입니다!")
            else:
                self.show_toast("현재 만화의 최초 에피소드(1화)입니다!")

    def sync_tree_selection(self, target_path):
        """에피소드 자동 전환 시 좌측 트리뷰에서도 해당 노드가 선택되도록 연동합니다."""
        for item in self.tree.get_children():
            # 만화 레벨 노드들 탐색
            for child in self.tree.get_children(item):
                path, _ = self.tree.item(child, "values")
                if path == target_path:
                    self.tree.selection_set(child)
                    self.tree.see(child)
                    return

    def toggle_direction(self):
        """읽기 방향을 RTL ↔ LTR 전환합니다."""
        if self.read_direction == "RTL":
            self.read_direction = "LTR"
            self.show_toast("정렬 방향: LTR (좌→우)")
        else:
            self.read_direction = "RTL"
            self.show_toast("정렬 방향: RTL (우→좌)")
        self.show_page(self.current_page)
        self.save_history()

    def toggle_view_mode(self):
        """보기 모드를 1페이지 ↔ 2페이지 전환합니다."""
        if self.view_mode == "2PAGE":
            self.view_mode = "1PAGE"
            self.show_toast("보기 모드: 1페이지 감상 (단면 1장 / 펼침면 분할)")
        else:
            self.view_mode = "2PAGE"
            self.show_toast("보기 모드: 2페이지 감상 (양면 Concat)")
        
        self.current_sub_page = 0
        self.show_page(self.current_page)
        self.save_history()

    def toggle_interface(self):
        """가운데 클릭 및 Tab 단축키에 대응해 좌측 사이드바와 하단 제어 툴바를 동시에 열거나 닫습니다."""
        # 하나라도 켜져 있다면 ➡️ 둘 다 끄기 (사용자 관점에서 닫힘 상태로 통일)
        if self.sidebar_visible or self.control_bar_visible:
            self.hide_interface()
        else:
            self.show_interface()

    def show_interface(self):
        """좌측 사이드바와 하단 툴바를 즉시 화면에 노출합니다."""
        # 1. 하단 툴바 노출
        self.show_control_bar()
        # 2. 좌측 사이드바 노출
        if not self.sidebar_visible:
            self.main_pane.add(self.sidebar, minsize=200)
            self.main_pane.paneconfigure(self.sidebar, before=self.viewer_frame)
            self.sidebar_visible = True
        self.save_history()

    def hide_interface(self):
        """좌측 사이드바와 하단 툴바를 즉시 화면에서 감춥니다."""
        # 1. 하단 툴바 은폐
        self.hide_control_bar()
        # 2. 좌측 사이드바 은폐
        if self.sidebar_visible:
            self.main_pane.forget(self.sidebar)
            self.sidebar_visible = False
        self.save_history()

    def toggle_sidebar(self):
        """기존 개별 사이드바 제어 메서드를 통합 인터페이스 토글로 호환 이식합니다."""
        self.toggle_interface()

    def toggle_fullscreen(self):
        """macOS 네이티브 전체화면을 토글하고, 진입 시 인터페이스를 자동으로 감춰 넓은 화면을 보장합니다."""
        self.fullscreen_active = not self.fullscreen_active
        self.root.attributes("-fullscreen", self.fullscreen_active)
        
        if self.fullscreen_active:
            # 전체화면 진입: 인터페이스가 켜져 있었다면 상태를 저장하고 전체 접기
            self.was_sidebar_visible = self.sidebar_visible
            self.hide_interface()
        else:
            # 전체화면 복귀: 전체화면 진입 전에 사이드바가 켜져 있었다면 원래대로 복원
            if hasattr(self, "was_sidebar_visible") and self.was_sidebar_visible:
                self.show_interface()
                    
        # 전체 화면 전환 후 렌더링 리드로우 유도
        self.root.after(100, lambda: self.show_page(self.current_page))

    def on_window_resize(self, event):
        """창 사이즈가 수정되면 이미지 해상도를 비례하여 재조정 렌더합니다."""
        # 캔버스가 리사이즈 이벤트의 발원지인지 식별
        if event.widget == self.canvas:
            # 잦은 리사이즈 중복 호출을 막기 위해 짧은 딜레이 후 렌더링
            if hasattr(self, "_resize_after_id"):
                self.root.after_cancel(self._resize_after_id)
            self._resize_after_id = self.root.after(80, lambda: self.show_page(self.current_page))

    def bind_events(self):
        # 1. 창 크기 변경 이벤트 연동
        self.canvas.bind("<Configure>", self.on_window_resize)
        
        # 2. 마우스 바인딩 (더블클릭 전체화면, 좌우 클릭, 모션 감지 및 마우스 휠 연동)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)  # 더블클릭 전용 검사기로 변경
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Motion>", self.on_canvas_motion)  # 마우스 모션 바인딩 추가
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)  # 마우스 휠 바인딩
        
        # 3. macOS 하드웨어 키코드 기반 물리 키캡 바인딩 (한/영 입력 소스 버그 완벽 해결)
        self.root.bind("<Key>", self.handle_global_key)

    def on_mouse_wheel(self, event):
        """
        마우스 휠/트랙패드 제스처를 감지하여 페이지를 전후로 전환합니다.
        macOS의 자연스러운 스크롤(Natural Scrolling) 직관에 부합하도록,
        위로 스크롤 시 이전 페이지, 아래로 스크롤 시 다음 페이지로 유기적 전환을 수행합니다.
        예민한 트랙패드 휠 입력을 조율하기 위해 0.5초(500ms) 디바운싱 잠금을 수행합니다.
        """
        current_time = time.time()
        # 0.5초 이내에 연속으로 들어오는 입력은 휠 굴림 관성으로 취급하여 차단
        if current_time - self.last_wheel_time < 0.5:
            return

        # macOS에서 위로 굴리면 event.delta > 0, 아래로 굴리면 event.delta < 0
        if event.delta > 0:
            self.prev_page()  # 자연스러운 스크롤 복원: 위로 굴리면 이전 장
            self.last_wheel_time = current_time
        elif event.delta < 0:
            self.next_page()  # 자연스러운 스크롤 복원: 아래로 굴리면 다음 장
            self.last_wheel_time = current_time

    def on_canvas_double_click(self, event):
        """
        화면 중앙 1/3 영역에서 더블클릭이 일어난 경우에만 전체화면을 토글합니다.
        좌우 1/3 영역(페이지 이동 영역)에서의 더블클릭 오작동을 원천 예방합니다.
        """
        canvas_width = max(self.canvas.winfo_width(), 100)
        one_third = canvas_width / 3
        
        # 가로 중앙 1/3 영역에서 더블클릭했을 때만 전체화면 토글 진행
        if one_third <= event.x <= one_third * 2:
            self.toggle_fullscreen()

    def on_canvas_click(self, event):
        """
        마우스 3분할 영역 클릭 감지기 (Left 1/3, Center 1/3, Right 1/3)
        - 제어 툴바(반투명 메뉴)가 노출된 상태에서 툴바 내부 클릭 시 정밀 좌표에 기반한 가상 버튼 기능(정렬, 보기모드, 전체닫기) 트리거
        - 일반 영역 클릭 시 가로 3등분에 따른 내비게이션(이전/다음 장 이동) 및 중앙 클릭 인터페이스 열기/닫기 토글 제어
        """
        canvas_width = max(self.canvas.winfo_width(), 100)
        canvas_height = max(self.canvas.winfo_height(), 100)

        # 1. 가상 제어 바(하단 반투명 메뉴)가 켜진 상태에서 메뉴 내부 영역 클릭 충돌 판정
        if self.control_bar_visible:
            bg_w = canvas_width * 0.85
            bg_h = 90
            bx = canvas_width / 2
            by = canvas_height * 0.88
            
            y_min = by - bg_h / 2
            y_max = by + bg_h / 2
            x_min = bx - bg_w / 2
            x_max = bx + bg_w / 2
            
            if y_min <= event.y <= y_max and x_min <= event.x <= x_max:
                # A. 정렬 버튼 영역 (x_min + 40 ~ x_min + 310)
                if x_min + 40 <= event.x <= x_min + 310:
                    self.toggle_direction()
                    return
                # B. 보기 모드 버튼 영역 (x_min + 320 ~ x_min + 490)
                elif x_min + 320 <= event.x <= x_min + 490:
                    self.toggle_view_mode()
                    return
                # D. 전체 닫기 버튼 영역 (x_max - 240 ~ x_max - 20)
                elif x_max - 240 <= event.x <= x_max - 20:
                    self.toggle_interface()
                    return
                # 그 외 제어바 빈 공간은 이벤트 흘림 차단
                return

        one_third = canvas_width / 3

        # 2. 클릭 위치가 중앙 1/3 영역인 경우 사이드바와 하단 제어 메뉴를 동시 토글 (오동작 완전 방지)
        if one_third <= event.x <= one_third * 2:
            self.toggle_interface()
            return

        is_left_click = event.x < one_third
        is_one_page_mode = (self.view_mode == "1PAGE")

        # 2. 감상 방향(RTL/LTR)에 맞춰 양끝 영역 클릭 시
        if is_one_page_mode:
            # 1페이지 모드에서는 분할 쪼개기 감상이 정상 보장되도록 next_page / prev_page 지능형 내비게이션 호출
            if self.read_direction == "RTL":
                if is_left_click:
                    self.next_page()
                else:
                    self.prev_page()
            else:
                if is_left_click:
                    self.prev_page()
                else:
                    self.next_page()
        else:
            # 2페이지 모드에서는 양면 짝 맞춤 수동 보정을 위해 기존대로 1페이지 단위 다이렉트 강제 이동 지원
            if self.read_direction == "RTL":
                if is_left_click:
                    # 좌측 1/3 클릭 ➡️ 다음 1페이지 (current_page + 1)
                    if self.current_page < len(self.image_files) - 1:
                        self.show_page(self.current_page + 1)
                    else:
                        self.switch_episode(direction=1)
                else:
                    # 우측 1/3 클릭 ➡️ 이전 1페이지 (current_page - 1)
                    if self.current_page > 0:
                        self.show_page(self.current_page - 1)
                    else:
                        self.switch_episode(direction=-1)
            else: # LTR 모드
                if is_left_click:
                    # 좌측 1/3 클릭 ➡️ 이전 1페이지
                    if self.current_page > 0:
                        self.show_page(self.current_page - 1)
                    else:
                        self.switch_episode(direction=-1)
                else:
                    # 우측 1/3 클릭 ➡️ 다음 1페이지
                    if self.current_page < len(self.image_files) - 1:
                        self.show_page(self.current_page + 1)
                    else:
                        self.switch_episode(direction=1)

    def on_canvas_motion(self, event):
        """가상 제어 바의 버튼 위에 마우스가 위치하면 텍스트 색상을 강조하고 커서를 hand2로 바꿉니다."""
        if not self.control_bar_visible:
            self.canvas.config(cursor="")
            return

        canvas_width = max(self.canvas.winfo_width(), 100)
        canvas_height = max(self.canvas.winfo_height(), 100)
        bg_w = canvas_width * 0.85
        bg_h = 90
        bx = canvas_width / 2
        by = canvas_height * 0.88

        y_min = by - bg_h / 2
        y_max = by + bg_h / 2
        x_min = bx - bg_w / 2
        x_max = bx + bg_w / 2

        on_button = False

        if y_min <= event.y <= y_max and x_min <= event.x <= x_max:
            # A. 정렬 버튼 영역 (x_min + 40 ~ x_min + 310)
            if x_min + 40 <= event.x <= x_min + 310:
                if hasattr(self, "_btn_align_id"):
                    self.canvas.itemconfig(self._btn_align_id, fill=self.accent_color)
                on_button = True
            else:
                if hasattr(self, "_btn_align_id"):
                    self.canvas.itemconfig(self._btn_align_id, fill=self.text_color)
            
            # B. 보기 모드 버튼 영역 (x_min + 320 ~ x_min + 490)
            if x_min + 320 <= event.x <= x_min + 490:
                if hasattr(self, "_btn_mode_id"):
                    self.canvas.itemconfig(self._btn_mode_id, fill=self.accent_color)
                on_button = True
            else:
                if hasattr(self, "_btn_mode_id"):
                    self.canvas.itemconfig(self._btn_mode_id, fill=self.text_color)

            # D. 전체 닫기 버튼 영역 (x_max - 240 ~ x_max - 20)
            if x_max - 240 <= event.x <= x_max - 20:
                if hasattr(self, "_btn_close_id"):
                    self.canvas.itemconfig(self._btn_close_id, fill=self.accent_color)
                on_button = True
            else:
                if hasattr(self, "_btn_close_id"):
                    self.canvas.itemconfig(self._btn_close_id, fill=self.text_color)
        else:
            # 전체 초기화
            if hasattr(self, "_btn_align_id"):
                self.canvas.itemconfig(self._btn_align_id, fill=self.text_color)
            if hasattr(self, "_btn_mode_id"):
                self.canvas.itemconfig(self._btn_mode_id, fill=self.text_color)
            if hasattr(self, "_btn_close_id"):
                self.canvas.itemconfig(self._btn_close_id, fill=self.text_color)

        if on_button:
            self.canvas.config(cursor="hand2")
        else:
            self.canvas.config(cursor="")

    def handle_global_key(self, event):
        """
        한글/영문 입력 소스 상태와 완전히 무관하게 작동하는 하드웨어 키코드 기반 글로벌 핸들러입니다.
        macOS의 가상 키코드(Virtual Keycode) 값과 표준 keysym 백업을 모두 결합하여 물리 키캡 기준으로 분기합니다.
        """
        keycode = event.keycode
        keysym = event.keysym

        # 1) F 또는 f 키 (macOS keycode = 3) -> 전체화면 토글
        if keycode == 3 or keysym in ("f", "F"):
            self.toggle_fullscreen()
            return "break"

        # 2) S 또는 s 키 (macOS keycode = 1) -> 짝맞춤 보정용 강제 1페이지 쉬프트 (Odd/Even Alignment Shift)
        elif keycode == 1 or keysym in ("s", "S"):
            if self.view_mode == "1PAGE":
                self.show_toast("1페이지 보기 모드에서는 짝맞춤 보정이 필요하지 않습니다.")
            else:
                if self.image_files and self.current_page < len(self.image_files) - 1:
                    self.show_page(self.current_page + 1)
                    self.show_toast("양면 짝맞춤 1페이지 보정 완료!")
            return "break"

        # 3) Escape 키 (macOS keycode = 53) -> 전체화면 탈출
        elif keycode == 53 or keysym == "Escape":
            if self.fullscreen_active:
                self.toggle_fullscreen()
            return "break"

        # 3) Tab 키 (macOS keycode = 48) -> 전체 인터페이스 열기/닫기
        elif keycode == 48 or keysym == "Tab":
            self.toggle_interface()
            return "break"

        # 3) [ 키 (macOS keycode = 33) -> 이전 에피소드
        elif keycode == 33 or keysym == "bracketleft":
            self.switch_episode(direction=-1)
            return "break"

        # 4) ] 키 (macOS keycode = 30) -> 다음 에피소드
        elif keycode == 30 or keysym == "bracketright":
            self.switch_episode(direction=1)
            return "break"

        # 5) Space 키 (macOS keycode = 49) -> 다음 페이지
        elif keycode == 49 or keysym == "space":
            self.next_page()
            return "break"

        # 6) BackSpace / Delete 키 (macOS keycode = 51) -> 이전 페이지
        elif keycode in (51, 117) or keysym in ("BackSpace", "Delete"):
            self.prev_page()
            return "break"

        # 7) 방향키 처리 (RTL 방향키 직관성 유지)
        elif keycode == 123 or keysym == "Left":
            self.handle_direction_key("Left")
            return "break"
        elif keycode == 124 or keysym == "Right":
            self.handle_direction_key("Right")
            return "break"
        elif keycode == 126 or keysym == "Up":
            self.prev_page()
            return "break"
        elif keycode == 125 or keysym == "Down":
            self.next_page()
            return "break"

    def handle_direction_key(self, key_name):
        """
        사용자의 공간 직관성에 맞게 물리적 방향키를 할당합니다.
        
        - RTL (우→좌 일본 만화 모드):
          * 우측 페이지로 시선을 이동하여 이전 장을 보려면 -> [우측 방향키 'Right'] 입력 (이전 페이지)
          * 좌측 페이지로 시선을 이동하여 다음 장을 보려면 -> [좌측 방향키 'Left'] 입력 (다음 페이지)
        - LTR (좌→우 일반 모드):
          * [우측 방향키 'Right'] 입력 -> 다음 페이지
          * [좌측 방향키 'Left'] 입력 -> 이전 페이지
        """
        if self.read_direction == "RTL":
            if key_name == "Left":
                self.next_page()
            elif key_name == "Right":
                self.prev_page()
        else:  # LTR 모드
            if key_name == "Left":
                self.prev_page()
            elif key_name == "Right":
                self.next_page()

    def save_history(self):
        """이어보기 환경을 기억하기 위해 로컬 JSON 히스토리를 갱신합니다."""
        history = {
            "root_dir": self.comic_root_dir,
            "current_comic": self.current_comic,
            "current_episode": self.current_episode,
            "current_page": self.current_page,
            "read_direction": self.read_direction,
            "view_mode": self.view_mode
        }
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"히스토리 저장 에러: {e}")

    def load_history(self):
        """저장되어 있는 이어보기 JSON 정보를 로드합니다."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    self.comic_root_dir = history.get("root_dir", self.comic_root_dir)
                    self.current_comic = history.get("current_comic", "")
                    self.current_episode = history.get("current_episode", "")
                    self.current_page = history.get("current_page", 0)
                    self.read_direction = history.get("read_direction", "RTL")
                    self.view_mode = history.get("view_mode", "2PAGE")
                    
                    # UI 버튼 레이블 동기화
                    if hasattr(self, "mode_btn"):
                        if self.view_mode == "1PAGE":
                            self.mode_btn.config(text="보기: 1페이지")
                        else:
                            self.mode_btn.config(text="보기: 2페이지")
            except Exception as e:
                print(f"히스토리 로드 실패: {e}")

    def restore_last_read(self):
        """히스토리로 최근에 보던 지점을 탐색해서 자동으로 열어줍니다."""
        if not self.current_comic or not self.current_episode:
            return

        # 트리에서 일치하는 회차 탐색
        for item in self.tree.get_children():
            comic_text = self.tree.item(item, "text").replace("📁 ", "")
            if comic_text == self.current_comic:
                self.tree.item(item, open=True) # 폴더 펼치기
                for child in self.tree.get_children(item):
                    ep_text = self.tree.item(child, "text").replace("📄 ", "")
                    if ep_text == self.current_episode:
                        self.tree.selection_set(child)
                        self.tree.see(child)
                        
                        # 이미지 및 페이지 로드
                        path, _ = self.tree.item(child, "values")
                        self.load_episode_images(path)
                        # 페이지 로딩 수행
                        if 0 <= self.current_page < len(self.image_files):
                            self.show_page(self.current_page)
                        else:
                            self.current_page = 0
                            self.show_page(0)
                        return


if __name__ == "__main__":
    root = tk.Tk()
    
    # macOS용 ttk 윈도우 스타일
    ttk_style = ttk.Style()
    ttk_style.theme_use("clam")
    
    app = ComicViewerGUI(root)
    
    def on_closing():
        app.preloader.stop()
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
