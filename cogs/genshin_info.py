import asyncio
import datetime
from typing import Literal, Optional, Sequence, Union

import discord
import genshin
import sentry_sdk
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from utility import EmbedTemplate, config, emoji
from utility.custom_log import LOG, ContextCommandLogger, SlashCommandLogger
from yuanshen import draw, genshin_app, parser


class RealtimeNotes:
    #即時便箋 real time notes

    @staticmethod
    async def notes(
        interaction: discord.Interaction,
        user: Union[discord.User, discord.Member],
        *,
        shortForm: bool = False,
    ):
        try:
            defer, notes = await asyncio.gather(
                interaction.response.defer(), genshin_app.get_realtime_notes(user.id)
            )
        except Exception as e:
            await interaction.edit_original_response(embed=EmbedTemplate.error(e))
        else:
            embed = await parser.parse_realtime_notes(notes, user=user, shortForm=shortForm)
            await interaction.edit_original_response(embed=embed)


class TravelerDiary:
    #旅行者札記 Traveler's Diary

    @staticmethod
    async def diary(
        interaction: discord.Interaction, user: Union[discord.User, discord.Member], month: int
    ):
        try:
            defer, diary = await asyncio.gather(
                interaction.response.defer(),
                genshin_app.get_traveler_diary(user.id, month),
            )
            embed = parser.parse_diary(diary, month)
        except Exception as e:
            await interaction.edit_original_response(embed=EmbedTemplate.error(e))
        else:
            embed.set_thumbnail(url=user.display_avatar.url)
            await interaction.edit_original_response(embed=embed)


class RecordCard:
    #遊戲紀錄卡片 Game Record Card

    @staticmethod
    async def card(
        interaction: discord.Interaction,
        user: Union[discord.User, discord.Member],
        option: Literal["RECORD", "EXPLORATION"],
    ):
        try:
            defer, (uid, userstats) = await asyncio.gather(
                interaction.response.defer(), genshin_app.get_record_card(user.id)
            )
        except Exception as e:
            await interaction.edit_original_response(embed=EmbedTemplate.error(e))
            return

        try:
            avatar_bytes = await user.display_avatar.read()
            if option == "RECORD":
                fp = draw.draw_record_card(avatar_bytes, uid, userstats)
            elif option == "EXPLORATION":
                fp = draw.draw_exploration_card(avatar_bytes, uid, userstats)
        except Exception as e:
            LOG.ErrorLog(interaction, e)
            sentry_sdk.capture_exception(e)
            await interaction.edit_original_response(embed=EmbedTemplate.error(e))
        else:
            fp.seek(0)
            await interaction.edit_original_response(
                attachments=[discord.File(fp=fp, filename="image.jpeg")]
            )
            fp.close()


class Characters:
    #角色一覽 Characters

    class Dropdown(discord.ui.Select):
        #選擇角色的下拉選單 Chratacter options

        def __init__(
            self,
            user: Union[discord.User, discord.Member],
            characters: Sequence[genshin.models.Character],
            index: int = 1,
        ):
            options = [
                discord.SelectOption(
                    label=f"★{c.rarity} C{c.constellation} Lv.{c.level} {c.name}",
                    description=(
                        f"★{c.weapon.rarity} R{c.weapon.refinement} "
                        f"Lv.{c.weapon.level} {c.weapon.name}"
                    ),
                    value=str(i),
                    emoji=emoji.elements.get(c.element.lower()),
                )
                for i, c in enumerate(characters)
            ]
            super().__init__(
                placeholder=f"select character: (number{index}~{index + len(characters) - 1})",
                min_values=1,
                max_values=1,
                options=options,
            )
            self.user = user
            self.characters = characters

        async def callback(self, interaction: discord.Interaction):
            embed = parser.parse_character(self.characters[int(self.values[0])])
            embed.set_author(
                name=f"{self.user.display_name}'s character",
                icon_url=self.user.display_avatar.url,
            )
            await interaction.response.edit_message(content=None, embed=embed)

    class DropdownView(discord.ui.View):
        #顯示角色下拉選單的View，依照選單欄位上限25個分割選單 display character dropdown view, max menu display slots are 25

        def __init__(
            self,
            user: Union[discord.User, discord.Member],
            characters: Sequence[genshin.models.Character],
        ):
            super().__init__(timeout=config.discord_view_long_timeout)
            max_row = 25
            for i in range(0, len(characters), max_row):
                self.add_item(Characters.Dropdown(user, characters[i : i + max_row], i + 1))

    @staticmethod
    async def characters(
        interaction: discord.Interaction, user: Union[discord.User, discord.Member]
    ):
        try:
            defer, characters = await asyncio.gather(
                interaction.response.defer(), genshin_app.get_characters(user.id)
            )
        except Exception as e:
            await interaction.edit_original_response(embed=EmbedTemplate.error(e))
        else:
            view = Characters.DropdownView(user, characters)
            await interaction.edit_original_response(content="Choose a character:", view=view)


class Notices:
    #原神遊戲內的遊戲與活動公告 Genshin game and event notices

    class Dropdown(discord.ui.Select):
        #選擇公告的下拉選單 Notice selection menu

        def __init__(self, notices: Sequence[genshin.models.Announcement], placeholder: str):
            self.notices = notices
            options = [
                discord.SelectOption(label=notice.subtitle, description=notice.title, value=str(i))
                for i, notice in enumerate(notices)
            ]
            super().__init__(placeholder=placeholder, options=options[:25])

        async def callback(self, interaction: discord.Interaction):
            notice = self.notices[int(self.values[0])]
            embed = EmbedTemplate.normal(
                parser.parse_html_content(notice.content), title=notice.title
            )
            embed.set_image(url=notice.banner)
            await interaction.response.edit_message(content=None, embed=embed)

    class View(discord.ui.View):
        def __init__(self):
            self.last_response_time: Optional[datetime.datetime] = None
            super().__init__(timeout=config.discord_view_long_timeout)

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            #避免短時間內太多人按導致聊天版面混亂 to prevent the chat crashing due to too much people interacting simultaneousl
            if (
                self.last_response_time is not None
                and (interaction.created_at - self.last_response_time).seconds < 3
            ):
                await interaction.response.send_message(
                    embed=EmbedTemplate.normal("too many user interactions, please try again later...."), ephemeral=True
                )
                return False
            else:
                self.last_response_time = interaction.created_at
                return True

    @staticmethod
    async def notices(interaction: discord.Interaction):
        try:
            defer, notices = await asyncio.gather(
                interaction.response.defer(), genshin_app.get_game_notices()
            )
        except Exception as e:
            await interaction.edit_original_response(embed=EmbedTemplate.error(e))
        else:
            # 將公告分成活動公告、遊戲公告、祈願公告三類 sort the game's notifications into 3 type: event notice, game notice, and wish notice
            game: list[genshin.models.Announcement] = []
            event: list[genshin.models.Announcement] = []
            wish: list[genshin.models.Announcement] = []
            for notice in notices:
                if notice.type == 1:
                    if "Wish" in notice.subtitle:
                        wish.append(notice)
                    else:
                        event.append(notice)
                elif notice.type == 2:
                    game.append(notice)

            view = Notices.View()
            if len(game) > 0:
                view.add_item(Notices.Dropdown(game, "Game Announcement:"))
            if len(event) > 0:
                view.add_item(Notices.Dropdown(event, "Event Announcement"))
            if len(wish) > 0:
                view.add_item(Notices.Dropdown(wish, "Banner Announcement:"))
            await interaction.edit_original_response(view=view)


class GenshinInfo(commands.Cog, name="Genshin info"):
    #"""斜線指令""" slash commands

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------
    # 取得使用者即時便箋資訊(樹脂、洞天寶錢、派遣...等) "obtain user's real-time traveler's diary info (resin, realm currency, expedition etc.
    @app_commands.command(name="Real Time Notes", description="check info about real-time notes, including resin, realm currency, expeditions etc.")
    @app_commands.rename(shortForm="display format", user="user")
    @app_commands.describe(shortForm="select full display or simplified display (will not display dailies, weeklies, expeditions))", user="check informtion of another user, will check current user's infor if no response is received.")
    @app_commands.choices(shortForm=[Choice(name="complete", value=0), Choice(name="simplefied", value=1)])
    @SlashCommandLogger
    async def slash_notes(
        self,
        interaction: discord.Interaction,
        shortForm: int = 0,
        user: Optional[discord.User] = None,
    ):
        await RealtimeNotes.notes(interaction, user or interaction.user, shortForm=bool(shortForm))

    # -------------------------------------------------------------
    # 取得使用者旅行者札記 obtain user's traveler's diary
    @app_commands.command(name="Traveler's Diary", description="check traveler's diary's info (primogems, mora)")
    @app_commands.rename(month="Month")
    @app_commands.describe(month="Choose a month")
    @app_commands.choices(
        month=[
            Choice(name="Current Month", value=0),
            Choice(name="Previous Month", value=-1),
            Choice(name="Two Months ago", value=-2),
        ]
    )
    @SlashCommandLogger
    async def slash_diary(self, interaction: discord.Interaction, month: int):
        month = datetime.datetime.now().month + month
        month = month + 12 if month < 1 else month
        await TravelerDiary.diary(interaction, interaction.user, month)

    # -------------------------------------------------------------
    # 產生遊戲紀錄卡片 generate game record card
    @app_commands.command(name="Record Card", description="generate personal genshin impact record card")
    @app_commands.rename(option="option", user="user")
    @app_commands.describe(option="check record data or exploration progress", user="check informtion of another user, will check current user's infor if no response is received.")
    @app_commands.choices(
        option=[
            Choice(name="Record Data", value="RECORD"),
            Choice(name="Exploration Progress", value="EXPLORATION"),
        ]
    )
    @app_commands.checks.cooldown(1, config.slash_cmd_cooldown)
    @SlashCommandLogger
    async def slash_card(
        self,
        interaction: discord.Interaction,
        option: Literal["RECORD", "EXPLORATION"],
        user: Optional[discord.User] = None,
    ):
        await RecordCard.card(interaction, user or interaction.user, option)

    @slash_card.error
    async def on_slash_card_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                embed=EmbedTemplate.error(f"Card Generation on cooldwon{config.slash_cmd_cooldown}seconds, try again later"),
                ephemeral=True,
            )

    # -------------------------------------------------------------
    # 個人所有角色一覽 Character Showcase
    @app_commands.command(name="characters", description="Publicky Display my characters")
    @SlashCommandLogger
    async def slash_characters(self, interaction: discord.Interaction):
        await Characters.characters(interaction, interaction.user)

    # -------------------------------------------------------------
    # 遊戲公告與活動公告 game announcements and event announcements
    @app_commands.command(name="Notices", description="display genshin impact's notices and event notices")
    @SlashCommandLogger
    async def slash_notices(self, interaction: discord.Interaction):
        await Notices.notices(interaction)


async def setup(client: commands.Bot):
    await client.add_cog(GenshinInfo(client))

    # -------------------------------------------------------------
    # 下面為Context Menu指令 context menu displayed at bottom
    @client.tree.context_menu(name="Real Time Notes")
    @ContextCommandLogger
    async def context_notes(interaction: discord.Interaction, user: discord.User):
        await RealtimeNotes.notes(interaction, user)

    @client.tree.context_menu(name="Record Card")
    @ContextCommandLogger
    async def context_card(interaction: discord.Interaction, user: discord.User):
        await RecordCard.card(interaction, user, "RECORD")
