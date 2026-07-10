import os
import sys
import queue
import threading
import tkinter as tk
import PIL._tkinter_finder
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse

# crawler 모듈에서 다운로드 함수 임포트
from crawler import download_board_images, download_series


class QueueRedirector:
    """sys.stdout/stderr 출력을 스레드 세이프하게 GUI 큐로 전달하는 클래스"""
    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, text):
        self.log_queue.put(text)

    def flush(self):
        pass


class ComicDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("일일툰 만화 다운로더 (macOS)")
        self.root.geometry("700x550")
        self.root.minsize(650, 480)

        # 시스템 기본 스트림 저장 (종료 시 복원용)
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr

        # 스레드 제어 변수
        self.log_queue = queue.Queue()
        self.download_thread = None
        self.is_downloading = False

        # UI 스타일 설정 (다크 테마)
        self.bg_color = "#1e1e1e"
        self.card_color = "#2a2a2a"
        self.accent_color = "#ff5a5f"  # 일일툰 어울리는 핑크레드
        self.accent_hover = "#e04f53"
        self.text_color = "#ffffff"
        self.sub_text = "#b3b3b3"
        self.input_bg = "#333333"

        # OS별 폰트 패밀리 자동 감정 설정
        import platform
        sys_name = platform.system()
        if sys_name == "Darwin":
            self.font_family = "Apple SD Gothic Neo"
        elif sys_name == "Windows":
            self.font_family = "Malgun Gothic"
        else:
            # Linux/Ubuntu: Xft/Fontconfig가 인식하는 한글 폰트 순회 탐색
            import tkinter.font as tkfont
            try:
                available = tkfont.families()
            except Exception:
                available = []
            candidates = ["Noto Sans CJK KR", "Noto Serif CJK KR", "NanumGothic", "sans-serif"]
            self.font_family = "sans-serif"
            for cand in candidates:
                if cand in available:
                    self.font_family = cand
                    break

        self.root.configure(bg=self.bg_color)
        self.setup_ui()

        # 출력 리다이렉트 설정
        sys.stdout = QueueRedirector(self.log_queue)
        sys.stderr = QueueRedirector(self.log_queue)

        # 로그 모니터링 루프 시작
        self.update_logs()

    def setup_ui(self):
        # 1. 상단 타이틀 영역
        title_frame = tk.Frame(self.root, bg=self.bg_color, pady=15)
        title_frame.pack(fill="x")
        
        title_label = tk.Label(
            title_frame,
            text="📖 일일툰 만화 다운로더",
            font=(self.font_family, 18, "bold"),
            fg=self.accent_color,
            bg=self.bg_color
        )
        title_label.pack(anchor="w", padx=20)
        
        desc_label = tk.Label(
            title_frame,
            text="회차 목록 주소를 입력하면 전체 에피소드를, 개별 회차 주소를 입력하면 단일 에피소드를 다운로드합니다.",
            font=(self.font_family, 11),
            fg=self.sub_text,
            bg=self.bg_color
        )
        desc_label.pack(anchor="w", padx=20, pady=2)

        # 2. 메인 입력 카드 영역
        card = tk.Frame(self.root, bg=self.card_color, bd=0, padx=20, pady=20)
        card.pack(fill="x", padx=20, pady=5)

        # URL 입력 필드
        url_label = tk.Label(
            card,
            text="만화 주소 (URL)",
            font=(self.font_family, 11, "bold"),
            fg=self.text_color,
            bg=self.card_color
        )
        url_label.pack(anchor="w", pady=(0, 5))

        url_frame = tk.Frame(card, bg=self.card_color)
        url_frame.pack(fill="x", pady=(0, 15))

        self.url_entry = tk.Entry(
            url_frame,
            font=(self.font_family, 11),
            fg=self.text_color,
            bg=self.input_bg,
            insertbackground="white",
            bd=1,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#444444",
            highlightcolor=self.accent_color
        )
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=6)
        # 테스트용 주소 기본 입력
        self.url_entry.insert(0, "http://103.204.13.68:8904/bbs/board.php?bo_table=toons&stx=%EB%8B%A4%EC%B9%B4%EC%8A%A4%EA%B8%B0%EA%B0%80%EC%9D%98%20%EB%8F%84%EC%8B%9C%EB%9D%BD&is=11838")

        # 클립보드 붙여넣기 커스텀 버튼 (macOS 다크 테마 완벽 호환)
        paste_btn = tk.Label(
            url_frame,
            text="📋 주소 붙여넣기",
            font=(self.font_family, 11),
            fg=self.text_color,
            bg="#444444",
            cursor="hand2",
            padx=15,
            pady=5,
            relief="flat",
            bd=0
        )
        paste_btn.pack(side="right", padx=(10, 0), ipady=2)
        paste_btn.bind("<Button-1>", lambda e: self.paste_url_from_clipboard())
        paste_btn.bind("<Enter>", lambda e: paste_btn.config(bg="#555555"))
        paste_btn.bind("<Leave>", lambda e: paste_btn.config(bg="#444444"))

        # 다운로드 경로 설정 필드
        path_label = tk.Label(
            card,
            text="다운로드 저장 경로",
            font=(self.font_family, 11, "bold"),
            fg=self.text_color,
            bg=self.card_color
        )
        path_label.pack(anchor="w", pady=(0, 5))

        path_frame = tk.Frame(card, bg=self.card_color)
        path_frame.pack(fill="x")

        self.path_entry = tk.Entry(
            path_frame,
            font=(self.font_family, 11),
            fg=self.text_color,
            bg=self.input_bg,
            insertbackground="white",
            bd=1,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#444444",
            highlightcolor=self.accent_color
        )
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=6)
        
        # 기본 다운로드 경로 설정
        default_path = "/Volumes/MacSSD/Comics"
        self.path_entry.insert(0, default_path)

        # macOS에서 배경색이 무시되는 tkinter Button 대신 Label을 사용하여 커스텀 플랫 버튼 구현
        browse_btn = tk.Label(
            path_frame,
            text="폴더 선택",
            font=(self.font_family, 11),
            fg=self.text_color,
            bg="#444444",
            cursor="hand2",
            padx=15,
            pady=5,
            relief="flat",
            bd=0
        )
        browse_btn.pack(side="right", padx=(10, 0), ipady=2)
        browse_btn.bind("<Button-1>", lambda e: self.browse_folder())
        browse_btn.bind("<Enter>", lambda e: browse_btn.config(bg="#555555"))
        browse_btn.bind("<Leave>", lambda e: browse_btn.config(bg="#444444"))

        # 3. 제어 버튼 및 상태
        btn_frame = tk.Frame(self.root, bg=self.bg_color, pady=10)
        btn_frame.pack(fill="x", padx=20)

        # 다운로드 버튼도 Label 기반 커스텀 버튼으로 적용하여 macOS 다크 테마 색상 지원
        self.download_btn = tk.Label(
            btn_frame,
            text="🚀 다운로드 시작",
            font=(self.font_family, 12, "bold"),
            fg=self.text_color,
            bg=self.accent_color,
            cursor="hand2",
            padx=20,
            pady=8,
            relief="flat",
            bd=0
        )
        self.download_btn.pack(side="right")
        self.download_btn.bind("<Button-1>", lambda e: self.start_download())
        self.download_btn.bind("<Enter>", lambda e: self.download_btn.config(bg=self.accent_hover) if not self.is_downloading else None)
        self.download_btn.bind("<Leave>", lambda e: self.download_btn.config(bg=self.accent_color) if not self.is_downloading else None)

        # 📂 폴더 열기 버튼 추가 (macOS 다크 테마 지원 라벨 형태)
        self.open_folder_btn = tk.Label(
            btn_frame,
            text="📂 폴더 열기",
            font=(self.font_family, 12, "bold"),
            fg=self.text_color,
            bg="#444444",
            cursor="hand2",
            padx=15,
            pady=8,
            relief="flat",
            bd=0
        )
        self.open_folder_btn.pack(side="right", padx=(0, 10))
        self.open_folder_btn.bind("<Button-1>", lambda e: self.open_download_folder())
        self.open_folder_btn.bind("<Enter>", lambda e: self.open_folder_btn.config(bg="#555555"))
        self.open_folder_btn.bind("<Leave>", lambda e: self.open_folder_btn.config(bg="#444444"))

        self.status_label = tk.Label(
            btn_frame,
            text="대기 중...",
            font=(self.font_family, 11),
            fg=self.sub_text,
            bg=self.bg_color
        )
        self.status_label.pack(side="left", pady=10)

        # 4. 실시간 로그 출력 영역
        log_frame = tk.Frame(self.root, bg=self.bg_color, padx=20, pady=10)
        log_frame.pack(fill="both", expand=True)

        log_title = tk.Label(
            log_frame,
            text="📋 실행 실시간 로그",
            font=(self.font_family, 11, "bold"),
            fg=self.text_color,
            bg=self.bg_color
        )
        log_title.pack(anchor="w", pady=(0, 5))

        self.log_text = tk.Text(
            log_frame,
            font=("Consolas", 10) if os.name == "nt" else ("Courier", 11),
            fg="#a9b7c6",
            bg="#121212",
            insertbackground="white",
            bd=0,
            relief="flat",
            state="disabled",
            highlightthickness=1,
            highlightbackground="#333333"
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview, bg="#121212")
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

    def paste_url_from_clipboard(self):
        """클립보드에서 텍스트를 가져와 주소창에 자동으로 붙여넣습니다."""
        try:
            clipboard_text = self.root.clipboard_get().strip()
            if clipboard_text:
                self.url_entry.delete(0, "end")
                self.url_entry.insert(0, clipboard_text)
                print(f"클립보드에서 주소를 붙여넣었습니다: {clipboard_text}")
        except Exception as e:
            messagebox.showwarning("경고", "클립보드에서 텍스트를 가져올 수 없습니다. 복사된 텍스트가 있는지 확인해 주세요.")

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=os.getcwd())
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def open_download_folder(self):
        """지정된 다운로드 폴더를 OS 파일 탐색기(Finder 등)로 엽니다."""
        folder = self.path_entry.get().strip()
        if not folder:
            messagebox.showerror("오류", "지정된 다운로드 폴더 경로가 없습니다.")
            return

        if not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                messagebox.showerror("오류", f"폴더 생성 실패: {e}")
                return

        import platform
        import subprocess
        try:
            if platform.system() == "Darwin":  # macOS
                subprocess.run(["open", folder])
            elif platform.system() == "Windows":  # Windows
                os.startfile(folder)
            else:  # Linux
                subprocess.run(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("오류", f"폴더를 열지 못했습니다: {e}")

    def update_logs(self):
        """큐에서 새로운 로그 텍스트를 꺼내 화면에 갱신하는 메서드 (메인 루프에서 상시 작동)"""
        while True:
            try:
                text = self.log_queue.get_nowait()
                self.log_text.config(state="normal")
                
                # 만약 캐리지 리턴(\r)이 포함되어 있다면 마지막 줄을 덮어씁니다. (in-place 진행률 지원)
                if text.startswith("\r"):
                    self.log_text.delete("end-1c linestart", "end-1c")
                    self.log_text.insert("end-1c", text.lstrip("\r"))
                else:
                    self.log_text.insert("end", text)
                    
                self.log_text.see("end")
                self.log_text.config(state="disabled")
            except queue.Empty:
                break
        self.root.after(50, self.update_logs)

    def start_download(self):
        if self.is_downloading:
            messagebox.showwarning("진행 중", "이미 다운로드가 진행 중입니다.")
            return

        url = self.url_entry.get().strip()
        folder = self.path_entry.get().strip()

        if not url:
            messagebox.showerror("오류", "다운로드할 만화 주소(URL)를 입력해주세요.")
            return
        if not folder:
            messagebox.showerror("오류", "다운로드 저장 폴더 경로를 지정해주세요.")
            return

        # UI 상태 업데이트
        self.is_downloading = True
        self.download_btn.config(text="⏳ 다운로드 중...", bg="#555555", cursor="arrow")
        self.status_label.config(text="다운로드를 진행하는 중입니다...", fg=self.accent_color)
        
        # 로그 클리어
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        # 다운로드 작업을 백그라운드 스레드에서 실행 (GUI 정지 방지)
        self.download_thread = threading.Thread(
            target=self.run_download_task,
            args=(url, folder),
            daemon=True
        )
        self.download_thread.start()

    def run_download_task(self, url, folder):
        try:
            if "wr_id=" in url:
                print(f"[단일 회차 다운로드 모드 시작]\nURL: {url}\n저장위치: {folder}\n")
                download_board_images(url, download_folder=folder)
            else:
                print(f"[전체 시리즈 다운로드 모드 시작]\nURL: {url}\n저장위치: {folder}\n")
                download_series(url, base_folder=folder)
            
            self.root.after(0, self.on_download_complete, True, "다운로드가 모두 완료되었습니다!")
        except Exception as e:
            self.root.after(0, self.on_download_complete, False, f"에러가 발생했습니다:\n{str(e)}")

    def on_download_complete(self, success, message):
        self.is_downloading = False
        self.download_btn.config(text="🚀 다운로드 시작", bg=self.accent_color, cursor="hand2")
        
        if success:
            self.status_label.config(text="다운로드 완료", fg="#10a37f")
            messagebox.showinfo("완료", message)
        else:
            self.status_label.config(text="오류 발생", fg="#ff5a5f")
            messagebox.showerror("에러", message)

    def restore_streams(self):
        """종료 시 원래의 stdout/stderr 스트림 복구"""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr


if __name__ == "__main__":
    root = tk.Tk()
    
    # macOS 특화 상단 메뉴 바 등의 기본 테마 적용
    style = ttk.Style()
    style.theme_use("clam")
    
    app = ComicDownloaderGUI(root)
    
    def on_closing():
        app.restore_streams()
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
