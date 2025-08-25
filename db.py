
def update_user_studying_status(message, supabase_client):
    # Update the user's studying status in the database
    from supabase import create_client, Client

    # Update the user's studying status to true
    response = supabase_client.table("users").update({
                        "studying" : true
                    }).eq(
                        "id", message.author.id
                        ).execute()