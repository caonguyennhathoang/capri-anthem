"""Paginated user guide for Capri Anthem."""

import discord
from discord import app_commands

from levels import (FIRST_LEVEL_XP, LEVEL_STEP_XP, LISTENING_MS_PER_XP,
                    XP_PER_ORDER, XP_PER_COMPLETION, XP_PER_HACK, level_threshold)
from music import HACK_CHANCE, HACK_COOLDOWN_SECONDS, MAX_QUEUE


def help_pages():
    per_minute = 60000 // LISTENING_MS_PER_XP
    sections = [
        ("Phát nhạc và điều khiển",
         "Vào kênh thoại trước, rồi dùng lệnh. Bot cần quyền Xem kênh, Kết nối, Nói và gửi tin nhắn.\n\n"
         "**`/play query:…`** — Nhập tên bài/nghệ sĩ, chọn kết quả trong 90 giây; hoặc dùng link một video YouTube.\n"
         "**`/random keyword:lofi count:5`** — Chọn ngẫu nhiên 1–10 bài trong tối đa 30 kết quả theo từ khóa; mặc định 5 bài.\n"
         "**`/queue`** — Xem bài đang phát và danh sách chờ.\n"
         "**`/pause` / `/resume`** — Tạm dừng / tiếp tục.\n"
         "**`/skip`** — Bỏ qua bài đang phát hoặc tải.\n"
         "**`/stop`** — Dừng nhạc và xóa hàng đợi.\n"
         "**`/join` / `/leave`** — Vào / rời kênh thoại của bạn.\n"
         "Bot tự rời và báo lý do trong chat sau 1 phút kênh không có người, hoặc 10 phút không phát nhạc và hàng đợi trống.\n"
         "Các nút dưới bài đang phát có tạm dừng, bỏ bài, dừng, hàng đợi, lặp bài và lưu vào playlist. "
         "Điều khiển nhạc yêu cầu bạn ở cùng kênh thoại với bot. "
         f"Hàng đợi tối đa {MAX_QUEUE} bài; thanh thời gian cập nhật mỗi 10 giây. Livestream chưa được hỗ trợ."),
        ("Tạo và quản lý playlist",
         "**`/playlist create name:… visibility:…`** — Tạo playlist, mặc định riêng tư.\n"
         "Bấm **Lưu vào playlist** dưới bài đang phát rồi nhập tên playlist của bạn để thêm bài.\n\n"
         "**`/playlist info`** — Xem các playlist của bạn. Chọn playlist để xem bài, số trang và trạng thái.\n"
         "**`/playlist info name:…`** — Mở playlist của bạn theo tên.\n"
         "**`/playlist info public_id:…`** — Xem playlist công khai theo mã; chỉ chọn một trong tên hoặc mã.\n"
         "Trong playlist của mình, chọn bài rồi bấm **Xóa bài** hoặc **Đổi vị trí**. Dùng nút trang trước/sau để lướt.\n\n"
         "**`/playlist visibility name:… visibility:…`** — Chuyển Công khai / Riêng tư.\n"
         "**`/playlist public`** — Tìm playlist công khai và mã ID. Có thể chọn `page` để xem tiếp.\n"
         "**`/playlist delete name:…`** — Xóa playlist của bạn cùng danh sách bài trong đó.\n\n"
         "Mỗi người có thể dùng cùng tên playlist với người khác. Chỉ chủ playlist được sửa/xóa. "
         "Playlist công khai cho mọi người xem và phát bằng ID. Mã ID xuất hiện khi công khai và trong `/playlist info`."),
        ("Phát playlist và sự kiện Capri Hack",
         "**`/playlist play name name:… order:…`** — Phát playlist của bạn.\n"
         "**`/playlist play public public_id:… order:…`** — Phát playlist công khai theo mã.\n"
         "Chọn **Theo thứ tự** (mặc định) hoặc **Xáo trộn** trong `order`. Các bài được thêm vào hàng đợi hiện tại, "
         "chỉ thêm đến khi hàng đợi đầy.\n\n"
         "**Capri Hack** có thể tự chen một bài liên quan ngay sau khi bài hiện tại kết thúc tự nhiên, trước các bài chờ. "
         f"Tỉ lệ thử là {HACK_CHANCE:.0%}, thời gian chờ giữa các lần thành công là {HACK_COOLDOWN_SECONDS // 60} phút. "
         "Bot chọn cùng nghệ sĩ và kiểu nhạc với bài thường gần nhất. Nếu thiếu thông tin hoặc không tìm được bài phù hợp, bot bỏ qua lượt Hack. "
         "Cần có người đang bật nghe trong kênh.\n\n"
         "Playlist lưu thông tin và link bài; khi phát, bot mới lấy âm thanh từ YouTube."),
        ("Luật cộng XP",
         f"**XP nghe — {per_minute} XP/phút**\n"
         "Chỉ tính khi bot đang phát nhạc, bạn cùng kênh thoại và đang bật nghe. "
         "Tạm dừng, hết nhạc, rời kênh hoặc tắt nghe thì ngừng cộng. Tắt mic vẫn nhận XP. "
         "Thời gian đủ điều kiện được cộng dồn, kể cả phần lẻ. Bot khác không nhận XP.\n\n"
         f"**Order — +{XP_PER_ORDER} XP/bài**\n"
         "Cộng khi bài được thêm thành công từ `/play` hoặc phát playlist. Bài không thêm được do hàng đợi đầy không tính.\n\n"
         f"**Nghe trọn bài — +{XP_PER_COMPLETION} XP cho người order**\n"
         "Người yêu cầu phải ở cùng kênh và bật nghe từ lúc bài bắt đầu đến khi kết thúc tự nhiên. "
         "Rời kênh hoặc tắt nghe giữa bài sẽ mất thưởng, kể cả quay lại. Tạm dừng vẫn giữ điều kiện nếu bạn còn ở đó và bật nghe. "
         "Skip, dừng hoặc phát lỗi không nhận thưởng nghe hết. Lặp lại bài không cộng lại order hay thưởng.\n\n"
         "**Bài từ `/random` chỉ tính XP nghe theo thời gian.** "
         "Không cộng điểm order hoặc thưởng nghe trọn bài. Bài gọi bằng `/play` sau đó vẫn tính điểm bình thường.\n\n"
         f"**Capri Hack — +{XP_PER_HACK} XP/người có mặt khi kết thúc tự nhiên**\n"
         "Khi bài Hack kết thúc tự nhiên, bạn đang cùng kênh và bật nghe sẽ nhận thưởng, kể cả vào giữa bài. "
         "Skip, dừng hoặc lỗi không thưởng. Nhạc Hack vẫn cộng XP thời gian nghe, không có điểm order hoặc thưởng 5 XP.\n\n"
         f"Ví dụ bài thường dài 1 phút: order +{XP_PER_ORDER}, nghe +{per_minute}, nghe hết +{XP_PER_COMPLETION} "
         f"= **{XP_PER_ORDER + per_minute + XP_PER_COMPLETION} XP**. "
         f"Nếu skip sau đúng 1 phút nghe: **{XP_PER_ORDER + per_minute} XP**. "
         f"Nghe một bài random đủ 1 phút: **{per_minute} XP**."),
        ("Cấp độ, danh hiệu và khung",
         "**`/rank`** — Xem XP, cấp độ, thời gian nghe, số bài order và hạng trong server. "
         "Chọn `member` để xem người khác. Nút **Đổi danh hiệu** cho xem trước và trang bị danh hiệu đã mở. "
         "Chọn **Tự động** để dùng danh hiệu cao nhất đã mở.\n\n"
         "**`/leaderboard`** — Top 10 người nghe trong server, xếp theo tổng XP. "
         "Nếu bằng XP, so thời gian nghe rồi ID người dùng.\n"
         "**`/frames`** — Xem tất cả khung, kể cả chưa mở; có menu, nút Trước/Sau và điều kiện cấp/XP.\n\n"
         f"Cấp 1 cần **{FIRST_LEVEL_XP} XP**. Mỗi bước lên cấp sau cần thêm **{LEVEL_STEP_XP} XP** so với bước trước. "
         f"Tổng XP để đạt cấp n = {FIRST_LEVEL_XP} × n + {LEVEL_STEP_XP} × n × (n − 1) ÷ 2.\n"
         f"Cấp 10: **{level_threshold(10):,} XP** · Cấp 50: **{level_threshold(50):,} XP** · "
         f"Cấp 100: **{level_threshold(100):,} XP**. Cấp độ không giới hạn.\n\n"
         "Danh hiệu mở tự động khi đủ cấp; bạn chọn lại bất kỳ danh hiệu đã sở hữu. "
         "XP, thời gian nghe và thứ hạng được lưu riêng theo server.\n\n"
         "**`/help`** — Mở lại hướng dẫn này. Dùng menu chọn chủ đề hoặc nút Trước/Sau."),
    ]
    pages = []
    for index, (title, text) in enumerate(sections, 1):
        embed = discord.Embed(title=title, description=text, color=0xFF2868)
        embed.set_footer(text=f"Capri Anthem · Hướng dẫn {index}/{len(sections)}")
        pages.append(embed)
    return pages


class HelpView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.pages = help_pages()
        self.index = 0
        self.topic.options = [discord.SelectOption(label=p.title, value=str(i))
                              for i, p in enumerate(self.pages)]
        self.update_controls()

    def update_controls(self):
        self.previous.disabled = self.index == 0
        self.next_page.disabled = self.index == len(self.pages) - 1
        for i, option in enumerate(self.topic.options):
            option.default = i == self.index

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Dùng /help để mở hướng dẫn của bạn.", ephemeral=True)
        return False

    async def show(self, interaction, index):
        self.index = max(0, min(len(self.pages) - 1, index))
        self.update_controls()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.select(placeholder="Chọn nội dung hướng dẫn", row=0)
    async def topic(self, interaction, menu):
        await self.show(interaction, int(menu.values[0]))

    @discord.ui.button(label="Trước", emoji="◀️", row=1)
    async def previous(self, interaction, button):
        await self.show(interaction, self.index - 1)

    @discord.ui.button(label="Sau", emoji="▶️", row=1)
    async def next_page(self, interaction, button):
        await self.show(interaction, self.index + 1)


def install_help(tree):
    @tree.command(name="help", description="Hướng dẫn tất cả lệnh và luật cộng XP của Capri Anthem")
    @app_commands.guild_only()
    async def help_command(interaction: discord.Interaction):
        view = HelpView(interaction.user.id)
        await interaction.response.send_message(embed=view.pages[0], view=view, ephemeral=True)
