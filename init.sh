echo '{"warnings": {}, "banned": {}, "restricted_users": {"no_links": {}, "fully_restricted": {}, "no_forwards": {}}, "user_stats": {}}' > /app/data/moderation_data.json
echo '{}' > /app/user_stats.json
touch /app/moderation.log
chmod 666 /app/*.json
chmod 666 /app/*.log
exec python bot.py
