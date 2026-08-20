var $result : Object

$result:=CLD2("This is a test in English and it should be detected correctly.")
ASSERT($result.language="en"; "Expected English, got: "+$result.language)
ASSERT($result.reliable=True; "Expected reliable detection")
ASSERT($result.textBytes>0; "Expected textBytes > 0")
ASSERT($result.languages#Null; "Expected languages collection")

$result:=CLD2("これは日本語のテストです。言語検出が正しく動作するか確認します。")
ASSERT($result.language="ja"; "Expected Japanese, got: "+$result.language)
