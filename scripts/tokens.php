<?php
/*
| Tokenize a PHP file and print the tokens as JSON
|
| The analyzer matches on tokens instead of running a regular expression over
| the source, a regular expression finds the word system inside a comment or a
| string and misses eval when it's written with a strange spacing
|
| Usage: php tokens.php <file>
*/

if ($argc < 2) {
	fwrite(STDERR, "usage: php tokens.php <file>\n");
	exit(2);
}

$source = @file_get_contents($argv[1]);
if ($source === false) {
	fwrite(STDERR, "unable to read " . $argv[1] . "\n");
	exit(2);
}

$tokens = @token_get_all($source);
if (!is_array($tokens)) {
	fwrite(STDERR, "unable to tokenize " . $argv[1] . "\n");
	exit(2);
}

$out = array();
$line = 1;
foreach ($tokens as $token) {
	if (is_array($token)) {
		$out[] = array(
			'name' => token_name($token[0]),
			'text' => $token[1],
			'line' => $token[2]
		);
		$line = $token[2];
	} else {
		// Single character tokens such as ( ) ; have no line number
		$out[] = array(
			'name' => 'CHAR',
			'text' => $token,
			'line' => $line
		);
	}
}

echo json_encode($out);
