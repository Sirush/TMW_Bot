from lib.bot import TMWBot
from lib.anilist_autocomplete import CACHED_ANILIST_RESULTS_CREATE_TABLE_QUERY, CACHED_ANILIST_THUMBNAIL_QUERY, CACHED_ANILIST_TITLE_QUERY, CREATE_ANILIST_FTS5_TABLE_QUERY, CREATE_ANILIST_TRIGGER_DELETE, CREATE_ANILIST_TRIGGER_INSERT, CREATE_ANILIST_TRIGGER_UPDATE
from lib.vndb_autocomplete import CACHED_VNDB_RESULTS_CREATE_TABLE_QUERY, CACHED_VNDB_THUMBNAIL_QUERY, CACHED_VNDB_TITLE_QUERY, CREATE_VNDB_FTS5_TABLE_QUERY, CREATE_VNDB_TRIGGER_DELETE, CREATE_VNDB_TRIGGER_INSERT, CREATE_VNDB_TRIGGER_UPDATE
from lib.tmdb_autocomplete import CACHED_TMDB_RESULTS_CREATE_TABLE_QUERY, CACHED_TMDB_THUMBNAIL_QUERY, CACHED_TMDB_TITLE_QUERY, CREATE_TMDB_FTS5_TABLE_QUERY, CREATE_TMDB_TRIGGER_DELETE, CREATE_TMDB_TRIGGER_INSERT, CREATE_TMDB_TRIGGER_UPDATE, CACHED_TMDB_GET_MEDIA_TYPE_QUERY
from lib.media_types import MEDIA_TYPES, LOG_CHOICES
from .immersion_goals import check_goal_status

import discord
import os
import yaml
import random
import csv
from typing import Optional
from datetime import timedelta, datetime
from discord.ext import commands
from discord.ext import tasks

SERVER_SETTINGS_PATH = os.getenv("ALT_SETTINGS_PATH") or "config/settings.yml"
with open(SERVER_SETTINGS_PATH, "r") as f:
    server_settings = yaml.safe_load(f)

CREATE_LOGS_TABLE = """
    CREATE TABLE IF NOT EXISTS logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    media_name TEXT,
    comment TEXT,
    amount_logged INTEGER NOT NULL,
    points_received REAL NOT NULL,
    log_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    achievement_group TEXT);
"""

CREATE_LOG_QUERY = """
    INSERT INTO logs (user_id, media_type, media_name, comment, amount_logged, points_received, log_date, achievement_group)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""

GET_CONSECUTIVE_DAYS_QUERY = """
    SELECT log_date
    FROM logs
    WHERE user_id = ?
    GROUP BY log_date
    ORDER BY log_date DESC;
"""

GET_POINTS_FOR_CURRENT_MONTH_QUERY = """
    SELECT SUM(points_received) AS total_points
    FROM logs
    WHERE user_id = ? AND strftime('%Y-%m', log_date) = strftime('%Y-%m', 'now');
"""

GET_USER_LOGS_QUERY = """
    SELECT log_id, media_type, media_name, amount_logged, log_date
    FROM logs
    WHERE user_id = ?
    ORDER BY log_date DESC;
"""

DELETE_LOG_QUERY = """
    DELETE FROM logs
    WHERE log_id = ? AND user_id = ?;
"""

GET_TOTAL_POINTS_FOR_ACHIEVEMENT_GROUP_QUERY = """
    SELECT SUM(points_received) AS total_points
    FROM logs
    WHERE user_id = ? AND achievement_group = ?;
"""

GET_USER_LOGS_FOR_EXPORT_QUERY = """
    SELECT log_id, media_type, media_name, comment, amount_logged, points_received, log_date
    FROM logs
    WHERE user_id = ?
    ORDER BY log_date DESC;
"""

ACHIEVEMENT_THRESHOLDS = [1, 100, 300, 1000, 2000, 10000, 25000, 100000]
ACHIEVEMENT_TITLES = ACHIEVEMENT_TITLES = [
    'Beginner 🌱',
    'Initiate ⚡️',
    'Apprentice 🎓',
    'Hobbyist 🥇',
    'Enthusiast 🔥',
    'Aficionado 🌟',
    'Sage 🤖',
    'Master 🏆'
]


async def log_undo_autocomplete(interaction: discord.Interaction, current_input: str):
    current_input = current_input.strip()

    tmw_bot = interaction.client
    tmw_bot: TMWBot

    user_logs = await tmw_bot.GET(GET_USER_LOGS_QUERY, (interaction.user.id,))
    choices = []

    for log_id, media_type, media_name, amount_logged, log_date in user_logs:
        unit_name = MEDIA_TYPES[media_type]['unit_name']
        log_date_str = datetime.strptime(log_date, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
        log_name = f"{media_type}: {media_name or 'N/A'} ({amount_logged} {unit_name}) on {log_date_str}"[:100]
        if current_input.lower() in log_name.lower():
            choices.append(discord.app_commands.Choice(name=log_name, value=str(log_id)))

    return choices[:10]


async def log_name_autocomplete(interaction: discord.Interaction, current_input: str):
    current_input = current_input.strip()
    if not current_input:
        return []
    if len(current_input) <= 1:
        return []
    media_type = interaction.namespace['media_type']
    if MEDIA_TYPES[media_type]['autocomplete']:
        result = await MEDIA_TYPES[media_type]['autocomplete'](interaction, current_input)
        return result
    return []


def is_valid_channel(interaction: discord.Interaction) -> bool:
    if interaction.channel.id in server_settings['immersion_bot']['allowed_log_channels']:
        return True
    if interaction.channel == interaction.user.dm_channel:
        return True
    return False


class ImmersionLog(commands.Cog):
    def __init__(self, bot: TMWBot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.RUN(CREATE_LOGS_TABLE)
        await self.bot.RUN(CACHED_ANILIST_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_ANILIST_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_ANILIST_TRIGGER_UPDATE)
        await self.bot.RUN(CACHED_VNDB_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_VNDB_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_VNDB_TRIGGER_UPDATE)
        await self.bot.RUN(CACHED_TMDB_RESULTS_CREATE_TABLE_QUERY)
        await self.bot.RUN(CREATE_TMDB_FTS5_TABLE_QUERY)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_DELETE)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_INSERT)
        await self.bot.RUN(CREATE_TMDB_TRIGGER_UPDATE)

    @discord.app_commands.command(name='log', description='Log your immersion!')
    @discord.app_commands.describe(
        media_type='The type of media you are logging.',
        amount='Amount. For time-based logs, use the number of minutes.',
        name='You can use VNDB ID/Title for VNs, AniList ID/Titlefor Anime/Manga, TMDB titles for Listening or provide free text.',
        comment='Short comment about your log.',
        backfill_date='The date for the log, in YYYY-MM-DD format. You can log no more than 7 days into the past.'
    )
    @discord.app_commands.choices(media_type=LOG_CHOICES)
    @discord.app_commands.autocomplete(name=log_name_autocomplete)
    async def log(self, interaction: discord.Interaction, media_type: str, amount: str, name: Optional[str], comment: Optional[str], backfill_date: Optional[str]):
        if not is_valid_channel(interaction):
            return await interaction.response.send_message("You can only use this command in DM or in the log channels.", ephemeral=True)
        if not amount.isdigit():
            return await interaction.response.send_message("Amount must be a valid number.", ephemeral=True)
        amount = int(amount)
        if amount < 0:
            return await interaction.response.send_message("Amount must be a positive number.", ephemeral=True)
        allowed_limit = MEDIA_TYPES[media_type]['max_logged']
        if amount > allowed_limit:
            return await interaction.response.send_message(f"Amount must be less than {allowed_limit} for `{MEDIA_TYPES[media_type]['log_name']}`.", ephemeral=True)

        if name and len(name) > 150:
            return await interaction.response.send_message("Name must be less than 150 characters.", ephemeral=True)
        if comment and len(comment) > 200:
            return await interaction.response.send_message("Comment must be less than 200 characters.", ephemeral=True)

        if backfill_date is None:
            log_date = discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        else:
            try:
                log_date = datetime.strptime(backfill_date, '%Y-%m-%d')
                today = discord.utils.utcnow().date()
                if log_date.date() > today:
                    return await interaction.response.send_message("You cannot log a date in the future.", ephemeral=True)
                if (today - log_date.date()).days > 7:
                    return await interaction.response.send_message("You cannot log a date more than 7 days in the past.", ephemeral=True)
                log_date = log_date.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                return await interaction.response.send_message("Invalid date format. Please use YYYY-MM-DD.", ephemeral=True)

        await interaction.response.defer()

        points_received = round(amount * MEDIA_TYPES[media_type]['points_multiplier'], 2)

        current_month_points_before = await self.get_points_for_current_month(interaction.user.id)

        await self.bot.RUN(
            CREATE_LOG_QUERY,
            (interaction.user.id, media_type, name, comment, amount,
             points_received, log_date, MEDIA_TYPES[media_type]['Achievement_Group'])
        )

        current_month_points_after = await self.get_points_for_current_month(interaction.user.id)

        goal_statuses = await check_goal_status(self.bot, interaction.user.id, media_type)

        achievement_group = MEDIA_TYPES[media_type]['Achievement_Group']
        total_achievement_points = await self.get_total_points_for_achievement_group(interaction.user.id, achievement_group)

        current_achievement = None
        next_achievement = None
        achievement_reached = False

        for threshold, title in zip(ACHIEVEMENT_THRESHOLDS, ACHIEVEMENT_TITLES):
            if total_achievement_points - points_received < threshold <= total_achievement_points:
                current_achievement = f"{achievement_group} {title}"
                achievement_reached = True
            elif total_achievement_points < threshold:
                next_achievement = f"{achievement_group} {title} at `{threshold}` {achievement_group} points (Current: `{round(total_achievement_points, 2)}`)"
                break

        if interaction.guild:
            random_guild_emoji = random.choice(interaction.guild.emojis)
        else:
            random_guild_emoji = ""

        consecutive_days = await self.get_consecutive_days_logged(interaction.user.id)
        actual_title = await self.get_title(media_type, name)
        thumbnail_url = await self.get_thumbnail_url(media_type, name)
        source_url = await self.get_source_url(media_type, name)

        embed_title = f"Logged {amount} {MEDIA_TYPES[media_type]['unit_name']}{
            's' if amount > 1 else ""} of {media_type} {random_guild_emoji}"
        log_embed = discord.Embed(title=embed_title, color=discord.Color.random())
        log_embed.description = f"[{actual_title}]({source_url})" if source_url else actual_title
        log_embed.add_field(name="Comment", value=comment or "No comment", inline=False)
        log_embed.add_field(name="Points Received", value=f"+{points_received}")
        log_embed.add_field(name="Total Points/Month",
                            value=f"{current_month_points_before} → {current_month_points_after}")
        log_embed.add_field(name="Streak", value=f"{consecutive_days} day{'s' if consecutive_days > 1 else ''}")
        if achievement_reached and current_achievement:
            log_embed.add_field(name="Achievement Reached! 🎉", value=current_achievement, inline=False)
        if next_achievement:
            log_embed.add_field(name="Next Achievement", value=next_achievement, inline=False)

        for i, goal_status in enumerate(goal_statuses, start=1):
            if len(log_embed.fields) >= 24:
                log_embed.add_field(name="Notice", value="You have reached the maximum number of fields. Please clear some of your goals to view more.", inline=False)
                break
            log_embed.add_field(name=f"Goal {i}", value=goal_status, inline=False)

        if thumbnail_url:
            log_embed.set_thumbnail(url=thumbnail_url)
        log_embed.set_footer(text=f"Logged by {interaction.user.display_name} for {backfill_date}", icon_url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=log_embed)

    async def get_consecutive_days_logged(self, user_id: int) -> int:
        result = await self.bot.GET(GET_CONSECUTIVE_DAYS_QUERY, (user_id,))
        if not result:
            return 0

        consecutive_days = 0
        today = discord.utils.utcnow().date()

        for row in result:
            log_date = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S').date()
            if log_date == today - timedelta(days=consecutive_days):
                consecutive_days += 1
            else:
                break

        return consecutive_days

    async def get_points_for_current_month(self, user_id: int) -> float:
        result = await self.bot.GET(GET_POINTS_FOR_CURRENT_MONTH_QUERY, (user_id,))
        if result and result[0] and result[0][0]:
            return round(result[0][0], 2)
        return 0.0

    async def get_thumbnail_url(self, media_type: str, name: str) -> Optional[str]:
        if MEDIA_TYPES[media_type]['thumbnail_query']:
            result = await self.bot.GET(MEDIA_TYPES[media_type]['thumbnail_query'], (name,))
            if result:
                return result[0][0]
        return None

    async def get_title(self, media_type: str, name: str) -> str:
        if MEDIA_TYPES[media_type]['title_query']:
            result = await self.bot.GET(MEDIA_TYPES[media_type]['title_query'], (name,))
            if result:
                return result[0][0]
        return name

    async def get_source_url(self, media_type: str, name: str) -> Optional[str]:
        if not MEDIA_TYPES[media_type]['source_url']:
            return None
        exists_in_db = await self.bot.GET(MEDIA_TYPES[media_type]['title_query'], (name,))
        if not exists_in_db:
            return None
        if media_type == "Listening Time":
            tmdb_media_type = await self.bot.GET(CACHED_TMDB_GET_MEDIA_TYPE_QUERY, (name,))
            tmdb_media_type = tmdb_media_type[0][0]
            return MEDIA_TYPES[media_type]['source_url'].format(tmdb_media_type=tmdb_media_type) + name
        return MEDIA_TYPES[media_type]['source_url'] + name

    @discord.app_commands.command(name='log_undo', description='Undo a previous immersion log!')
    @discord.app_commands.describe(log_entry='Select the log entry you want to undo.')
    @discord.app_commands.autocomplete(log_entry=log_undo_autocomplete)
    async def log_undo(self, interaction: discord.Interaction, log_entry: str):
        if not log_entry.isdigit():
            return await interaction.response.send_message("Invalid log entry selected.", ephemeral=True)

        log_id = int(log_entry)
        user_logs = await self.bot.GET(GET_USER_LOGS_QUERY, (interaction.user.id,))
        log_ids = [log[0] for log in user_logs]

        if log_id not in log_ids:
            return await interaction.response.send_message("The selected log entry does not exist or does not belong to you.", ephemeral=True)

        deleted_log_info = await self.bot.GET(GET_USER_LOGS_QUERY, (interaction.user.id,))
        log_id, media_type, media_name, amount_logged, log_date = deleted_log_info[0]
        log_date = datetime.strptime(log_date, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
        await self.bot.RUN(DELETE_LOG_QUERY, (log_id, interaction.user.id))
        await interaction.response.send_message(f"> {interaction.user.mention} Your log for `{amount_logged} {MEDIA_TYPES[media_type]['unit_name']}` of `{media_type}` (`{media_name if media_name else "No Name"}`) on `{log_date}` has been deleted.")

    async def get_total_points_for_achievement_group(self, user_id: int, achievement_group: str) -> float:
        result = await self.bot.GET(GET_TOTAL_POINTS_FOR_ACHIEVEMENT_GROUP_QUERY, (user_id, achievement_group))
        if result and result[0] and result[0][0] is not None:
            return result[0][0]
        return 0.0

    @discord.app_commands.command(name='log_achievements', description='Display all your achievements!')
    async def log_achievements(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        achievements_list = []
        for achievement_group in set(settings_group['Achievement_Group'] for settings_group in MEDIA_TYPES.values()):
            total_points = await self.get_total_points_for_achievement_group(user_id, achievement_group)
            for threshold, title in zip(ACHIEVEMENT_THRESHOLDS, ACHIEVEMENT_TITLES):
                if total_points >= threshold:
                    achievements_list.append(f"- {achievement_group} {title} - {threshold} points")
                else:
                    break

        if achievements_list:
            achievements_str = "\n".join(achievements_list)
        else:
            achievements_str = "No achievements yet. Keep immersing!"

        embed = discord.Embed(title=f"{interaction.user.display_name}'s Achievements",
                              description=achievements_str, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name='log_export', description='Export immersion logs as a CSV file! Optionally, specify a user ID to export their logs.')
    @discord.app_commands.describe(user='The user to export logs for (optional)')
    async def log_export(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        user_id = user.id if user else interaction.user.id
        user_logs = await self.bot.GET(GET_USER_LOGS_FOR_EXPORT_QUERY, (user_id,))

        if not user_logs:
            return await interaction.response.send_message("No logs to export for the specified user.", ephemeral=True)

        csv_filename = f"immersion_logs_{user_id}.csv"
        csv_filepath = os.path.join("/tmp", csv_filename)

        with open(csv_filepath, mode='w', newline='', encoding='utf-8') as csv_file:
            fieldnames = ['Log ID', 'Media Type', 'Media Name', 'Comment', 'Amount Logged', 'Points Received', 'Log Date']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            for log in user_logs:
                writer.writerow({
                    'Log ID': log[0],
                    'Media Type': log[1],
                    'Media Name': log[2] or 'N/A',
                    'Comment': log[3] or 'No comment',
                    'Amount Logged': log[4],
                    'Points Received': log[5],
                    'Log Date': log[6]
                })

        await interaction.response.send_message("Here are the immersion logs:", file=discord.File(csv_filepath))
        os.remove(csv_filepath)


async def setup(bot):
    await bot.add_cog(ImmersionLog(bot))