import discord
from discord.utils import get
from discord.ext import commands, tasks
import asyncio, logging
import os, json, textwrap, traceback 
from re import sub
from random import choice, random
from datetime import datetime, timedelta
from pymongo import MongoClient
from word2number import w2n
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
token = os.environ.get('DISCORDTOKEN')
intents = discord.Intents().default()
intents.members = True
bot = commands.Bot(command_prefix='$', intents=intents, help_command=None)
db_client = MongoClient('localhost',27017)
db = db_client["botsky"]

with open('activities.json') as f:
    activities = json.load(f)

### TASKS / EVENTS
@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} has connected to Discord!')
    change_presense.start()
    weekly_leaderboard.start()

async def is_admin(ctx):
    return ctx.author.guild_permissions.administrator or ctx.author.id == 184880932476420097

@tasks.loop(minutes=15)
async def change_presense():
    activity = discord.Game(choice(activities))
    await bot.change_presence(activity=activity)

@tasks.loop(hours=24*7)
async def weekly_leaderboard():  
    await sleep_until_hour(20)
    while datetime.now().weekday() != 6:
        await asyncio.sleep(24 * 60 * 60)
    coll = db['guild_parameters']
    for guild in bot.guilds:
        params = coll.find_one({"_id" : guild.id})
        if params and "announcements" in params and bot.get_channel(params["announcements"]) and "weekly-leaderboard_disable" not in params:
            await leaderboard_print(bot.get_channel(params["announcements"]), guild, 'weekly')

    


### EVENTS
@bot.event
async def on_message(message):
    # process all other commands first
    await bot.process_commands(message)
    if message.author.bot:
        return

    coll = db['guild_parameters']
    counting_channel = await db_get_channel(message.guild.id, 'counting')
    if not counting_channel:
        return
    if message.channel == counting_channel and "counting-errors_disable" not in coll.find_one({"_id" : message.guild.id}):
        coll = db['guild_message_history']
        coll.update_one({"_id" : message.guild.id}, {"$push" : {"messages" : [message.author.id, message.created_at]}}, upsert=True)
        latest_mesgs = [x.content for x in await counting_channel.history(limit=5).flatten() if "you've counted incorrectly" not in x.content.lower()]

        async def convert(n : str) -> int:
            """Converts n into an integer
            from str, binary, or written out text
            """
            async def is_binary(n : str):
                t = '01'
                for char in n:
                    if char not in t:
                        return False
                return True

            if await is_binary(n):
                return int(n, base=2)
            elif any(map(str.isdigit, n)):
                try: 
                    return int(sub("[^0-9]", "", n))
                except ValueError:
                    return 0
            else:
                try:
                    return w2n.word_to_num(n)
                except ValueError:
                    return 0

        if await convert(latest_mesgs[0]) != await convert(latest_mesgs[1]) + 1:
            mesg = message.author.mention + " You've counted incorrectly. Please fix your number."
            await counting_channel.send(mesg, delete_after=10)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("You don't have permission to run this command...")




### COMMANDS
@bot.command()
async def ping(ctx):
    await ctx.send(f'Pong! **{round(bot.latency, 3)}ms**.')

@bot.command()
async def help(ctx):
    embed=discord.Embed(title="⭐ botsky help ⭐", description="______", color=0x3498db)
    embed.add_field(name="$stats [optional: @user]", value="Displays the counting stats of either the user who called the command or whoever is mentioned.", inline=False)
    embed.add_field(name="$leaderboard [optional: daily/weekly/monthly/all]", value="Displays a 5 person leaderboard for the time period selected. If not time period is selected defaults to daily.", inline=False)
    embed.add_field(name="$link [counting/announcements]", value="Can only be run by an admin. This needs to be run prior to running the $stats or $leaderboard command. Links a counting channel or an announcements channel to send the weekly leaderboard.", inline=False)
    embed.add_field(name="$index-messages", value="Can only be run by an admin. This needs to be run prior to running the $stats or $leaderboard command. It may take a minute.", inline=False)
    embed.add_field(name="$enable/$disable [counting-errors/weekly-leaderboard]", value="Can only be run by an admin. Enable/Disable errors when someone counts incorrectly in the counting channel or the weekly leaderboard.", inline=False)
    embed.add_field(name="$feedback", value="Send feedback to Wesley, the creator of this bot.", inline=False)
    embed.add_field(name="$length", value="Self explanatory.", inline=False)
    embed.add_field(name="$ping", value="Self explanatory.", inline=False)
    embed.add_field(name="______", value="https://github.com/wesleynw/botsky", inline=False)
    await ctx.send(embed=embed)

@bot.command()
@commands.check(is_admin)
async def link(ctx, category : str, channel : discord.TextChannel):
    channel_types = ['counting', 'announcements']
    if category not in channel_types:
        raise commands.BadArgument
    coll = db['guild_parameters']
    coll.update_one({"_id" : ctx.guild.id}, {"$set" : {category : channel.id}}, upsert=True)
    await ctx.send(f"The {category} channel has been set to {channel.mention}")
@link.error
async def link_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("That channel or channel type doesn't exist...")

@bot.command()  
async def leaderboard(ctx, *args):
    await leaderboard_print(ctx.channel, ctx.guild, *args)
async def leaderboard_print(channel, guild, *args):
    coll = db['guild_parameters']
    counting_channel = await db_get_channel(guild.id, 'counting')
    if not counting_channel:
        await no_channel_set(channel, 'counting')
        return

    now = datetime.utcnow()
    interval = 'Daily'
    if len(args) >= 1:
        if args[0] == 'daily':
            td = timedelta(days=1)
            interval = 'Daily'
        elif args[0] == 'weekly':
            td = timedelta(weeks=1)
            interval = 'Weekly'
        elif args[0] == 'monthly':
            td = timedelta(weeks=4)
            interval = 'Monthly'
        elif args[0] == 'all':
            oldest_mesg = await counting_channel.history(limit=1, oldest_first=True).flatten()
            td = now - oldest_mesg[0].created_at    
            interval = "All Time"
        else:
            await channel.send("Something went wrong. Try running this command again. You must specify **weekly**, **monthly**, or **all**, or just **#leaderboard** for all time.")
            return
    else:
        td = timedelta(days=1)
        interval = 'Daily'

    now = datetime.utcnow()
    slowmode = counting_channel.slowmode_delay
    coll = db['guild_message_history']
    params = coll.find_one({"_id" : guild.id})
    if not (params and params.get('messages')):
        await channel.send("Please run **$index-messages** so I can view your past counting channel messages.")
    counting_channel_history = params.get('messages')

    ranks_and_efficiency = await calculate_member_stats(guild.members, None, counting_channel_history, slowmode, now - td)

    embed = discord.Embed(color=0x3498db)
    embed.add_field(name=f'{interval} Leaderboard 💯', value='___', inline=False)

    for i in range(min(5, len(ranks_and_efficiency))):
        place = i+1
        if place == 1:
            place = ":first_place:"
        elif place == 2:
            place = ":second_place:"
        elif place == 3:
            place = ":third_place:"
        embed.add_field(name=f"***{place}*** - {ranks_and_efficiency[i][1].display_name}", value=f"{await efficiency_bar(ranks_and_efficiency[i][2])} ({ranks_and_efficiency[i][2]}%)", inline=False)
    await channel.send(embed=embed)
    coll = db['guild_parameters']
    for guild in bot.guilds:
        opts = coll.find_one({"_id" : guild.id})
        if not (opts and "announcements" in opts  and bot.get_channel(opts["announcements"])):
            await no_channel_set(channel, 'announcements')

@bot.command(name='index-messages')
@commands.check(is_admin)
async def index_messages(ctx):
    counting_channel = await db_get_channel(ctx.guild.id, 'counting')
    if not counting_channel:
        await no_channel_set(ctx.channel, 'counting')
        return
    
    mesg = await ctx.channel.send(f"Please wait... Indexing 0 messages in {counting_channel.mention}")
    counter = 0
    coll = db["guild_message_history"]
    coll.delete_many({"_id" : ctx.guild.id})
    async for message in counting_channel.history(limit=None, oldest_first=True):
        # if message.author.bot:
        #     pass
        if counter % 10 == 0:
            await mesg.edit(content=f"Please wait... Indexing {counter} messages in {counting_channel.mention}")
        coll.update_one({"_id" : ctx.guild.id}, {"$push" : {"messages" : [message.author.id, message.created_at]}}, upsert=True)
        counter += 1
    await mesg.edit(content=f"Finished! Indexed {counter} messages in {counting_channel.mention}")

@bot.command()
async def stats(ctx, member : discord.Member = None):
    member = member or ctx.author 
    coll = db['guild_parameters']
    counting_channel = await db_get_channel(ctx.guild.id, 'counting')
    if not counting_channel:
        await no_channel_set(ctx.channel, 'counting')
        return
    slowmode = counting_channel.slowmode_delay

    coll = db['guild_message_history']
    params = coll.find_one({"_id" : ctx.guild.id})
    if not (params and params.get('messages')):
        await ctx.send("Please run **$index-messages** so I can view your past counting channel messages.")
    counting_channel_history = params.get('messages')

    now = datetime.utcnow()
    # returns in format: [member, rank, efficiency]
    daily_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(days=1))
    prev_daily_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(days=2), now - timedelta(days=1))
    weekly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=1))
    prev_weekly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=2), now - timedelta(weeks=1))

    monthly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=4))
    prev_monthly_stats = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, now - timedelta(weeks=8), now - timedelta(weeks=4))

    oldest_time = counting_channel_history[0][1]
    all_time = await calculate_member_stats(ctx.guild.members, member, counting_channel_history, slowmode, oldest_time)

    color = 0x3498db if member.color == discord.Color.default() else member.color
    embed = discord.Embed(color=color)
    embed.set_author(name=member.name+"'s stats", icon_url=member.avatar_url)
    embed.set_footer(text="Counted a total of " + str(all_time[3]) + " times.")

    daily_direction = 'Up' if daily_stats[2] > prev_daily_stats[2] else 'Down'
    daily_bar = await efficiency_bar(daily_stats[2]) + f" ({daily_stats[2]}%)"+f"\n```{daily_direction} {abs(round(daily_stats[2]-prev_daily_stats[2], 1))}% from yesterday```"
    embed.add_field(name="Daily - Ranked #"+str(daily_stats[1]), value=daily_bar)

    weekly_direction = 'Up' if weekly_stats[2] > prev_weekly_stats[2] else 'Down'
    weekly_bar = await efficiency_bar(weekly_stats[2]) + f" ({weekly_stats[2]}%)"+f"\n```{weekly_direction} {abs(round(weekly_stats[2]-prev_weekly_stats[2], 1))}% from last week```"
    embed.add_field(name='Weekly - Ranked #'+str(weekly_stats[1]), value=weekly_bar)

    monthly_direction = 'Up' if monthly_stats[2] > prev_monthly_stats[2] else 'Down'
    monthly_bar = await efficiency_bar(monthly_stats[2]) + f" ({monthly_stats[2]}%)"+f"\n```{monthly_direction} {abs(round( monthly_stats[2]-prev_monthly_stats[2], 1))}% from last month```"
    embed.add_field(name='Monthly - Ranked #'+str(monthly_stats[1]), value=monthly_bar)

    await ctx.send(embed=embed)
    coll = db['guild_parameters']
    for guild in bot.guilds:
        opts = coll.find_one({"_id" : guild.id})
        if not(opts and "announcements" in opts  and bot.get_channel(opts["announcements"])):
            await no_channel_set(ctx.channel, 'announcements')
@stats.error 
async def stats_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("That member doesn't exist...")

@bot.command()
async def length(ctx, member : discord.Member = None):
    member = member or ctx.author
    length = round(member.id / 10**17, 1)
    if member.id == 184880932476420097:
        length = 7
    elif member.id == 495824425711828993:
        length = 11.1
    await ctx.send(f"{member.mention}'s cock length is {length} inches.")

@bot.command()
@commands.check(is_admin)
async def enable(ctx, option):
    if option in ["weekly-leaderboard", "counting-errors"]:
        coll = db["guild_parameters"]
        coll.update_one({"_id" : ctx.guild.id}, {"$unset" : {option + "_disable" : ""}})
    else:
        raise commands.BadArgument
    await ctx.send('I have enabled for '+option)
@enable.error
async def enable_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"There was an error, please try again... You can use the enable command on **weekly-leaderboard** or **counting-errors**.")

@bot.command()
@commands.check(is_admin)
async def disable(ctx, option):
    if option in ["weekly-leaderboard", "counting-errors"]:
        coll = db['guild_parameters']
        coll.update_one({"_id" : ctx.guild.id}, {"$set" : {option + "_disable" : True}}, upsert=True)
    else:
        raise commands.BadArgument
    await ctx.send('I have disabled '+option)
@disable.error
async def disable_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"There was an error, please try again... You can use the disable command on **weekly-leaderboard** or **counting-errors**.")

@bot.command()
async def feedback(ctx):
    wesley = bot.get_user(184880932476420097)
    await wesley.send(ctx.message.content)




### FUNCTIONS
async def db_get_channel(guild_id : int, channel_type : str) -> discord.TextChannel:
    """Return discord.TextChannel instance of channel_type if it exists in the db."""
    coll = db['guild_parameters']
    params = coll.find_one({"_id" : guild_id})
    if params and channel_type in params and bot.get_channel(params[channel_type]):
        return bot.get_channel(params[channel_type])

async def set_announcements_channel_reminder(channel):
    await channel.send('By the way, you should link an announcements channel using **$link announcements *#channel*')
async def no_channel_set(mesg_channel : discord.TextChannel, category : str):
    """Send a message to mesg_channel announcing that a certain channel must be set."""
    if category == "counting":
        await mesg_channel.send('You must set a counting channel using **$link counting** ***#channel***.')
    elif category == "announcements":
        await mesg_channel.send('You must set an announcements channel using **$link announcements** ***#channel***.')

async def sleep_until_hour(hour : int):
    now = datetime.now()
    if now.hour != hour or now.minute != 0:
        if now.hour < hour:
            wait_until = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            await asyncio.sleep((wait_until - now).total_seconds())
        else:
            wait_until = now.replace(day=now.day+1, hour=hour, minute=0, second=0, microsecond=0)
            await asyncio.sleep((wait_until - now).total_seconds())

async def calculate_member_stats(members, req_member, channel_history, slowmode_delay, after, before=None):
    if before is None:
        before = datetime.utcnow()

    channel_history = [x[0] for x in channel_history if x[1] > after and x[1] < before]
    # .slowmode_delay is in seconds
    possible_counts_interval = round((before - after).total_seconds() / slowmode_delay)

    stats = []
    for member in members:
        counter = 0
        for message in channel_history:
            if message == member.id:
                counter +=1
        stats.append([member, round(counter / possible_counts_interval * 100, 2), counter])

    # sort efficiencies low to high
    efficiency_stats = sorted(stats, key=lambda x: x[1], reverse=True)

    # if req_member is set to None, then return all stats, sorted
    if req_member is None:
        ranks_and_efficiency = []
        for i in range(len(efficiency_stats)):
            # returns in format [ [rank, member, efficiency, total_counts], [], [] ]
            ranks_and_efficiency.append([i+1, efficiency_stats[i][0], efficiency_stats[i][1], efficiency_stats[i][2]])
        return ranks_and_efficiency
    else:
        for i,e in enumerate(efficiency_stats):
            if e[0] == req_member:
                # format: [member, rank, efficiency, total_counts]
                return [e[0], i+1, e[1], e[2]]

async def efficiency_bar(percent: float) -> str:
    """Returns a string of 10 full and empty squares representing the percent variable, where percent is a float > 0."""
    percent = round(percent/10)
    return '[■](https://youtu.be/dQw4w9WgXcQ)'*min(10, percent) + '[□](https://youtu.be/dQw4w9WgXcQ)'*(10-percent)




### RUN
bot.run(token)
